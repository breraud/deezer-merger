import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deezer_client import DeezerClient

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional until dependencies are installed
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False


LOGGER = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
STATE_FILE = ROOT_DIR / "state.json"
PLAYER_IDS = ("player1", "player2", "player3")
PLAYER_ENV_KEYS = {
    "player1": "PLAYLIST_SOURCE_1",
    "player2": "PLAYLIST_SOURCE_2",
    "player3": "PLAYLIST_SOURCE_3",
}


@dataclass
class Settings:
    deezer_arl: str
    source_playlists: dict[str, str]
    target_playlist: str

    @classmethod
    def from_env(cls) -> "Settings":
        import os

        load_dotenv()

        deezer_arl = os.getenv("DEEZER_ARL", "").strip()
        target_playlist = os.getenv("PLAYLIST_CIBLE", "").strip()
        source_playlists = {
            player_id: os.getenv(env_key, "").strip()
            for player_id, env_key in PLAYER_ENV_KEYS.items()
        }

        missing = [
            name
            for name, value in {
                "DEEZER_ARL": deezer_arl,
                "PLAYLIST_CIBLE": target_playlist,
                **{env_key: source_playlists[player_id] for player_id, env_key in PLAYER_ENV_KEYS.items()},
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        return cls(
            deezer_arl=deezer_arl,
            source_playlists=source_playlists,
            target_playlist=target_playlist,
        )


def _deduplicate(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduplicated: list[dict[str, str]] = []
    for item in items:
        track_id = item.get("id")
        if not track_id or track_id in seen:
            continue
        seen.add(track_id)
        deduplicated.append(item)
    return deduplicated


def _default_player_name(player_id: str) -> str:
    return f"Joueur {player_id.removeprefix('player')}"


def _normalize_track_list(items: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            track_id = item.get("id")
            if not track_id:
                continue
            normalized.append(
                {
                    "id": str(track_id),
                    "title": str(item.get("title") or ""),
                    "artist": str(item.get("artist") or ""),
                }
            )
        elif item is not None:
            normalized.append({"id": str(item), "title": "", "artist": ""})
    return normalized


def build_empty_state() -> dict[str, Any]:
    return {
        "source_pools": {player_id: [] for player_id in PLAYER_IDS},
        "players": {
            player_id: {"name": _default_player_name(player_id), "selection": []}
            for player_id in PLAYER_IDS
        },
        "mix": [],
    }


def load_state(state_path: Path = STATE_FILE) -> dict[str, Any]:
    if not state_path.exists():
        return build_empty_state()

    try:
        content = state_path.read_text(encoding="utf-8")
        if not content.strip():
            LOGGER.warning("State file at %s is empty. Falling back to default state.", state_path)
            return build_empty_state()
        data = json.loads(content)
    except OSError:
        LOGGER.warning("Unable to read state file at %s. Falling back to default state.", state_path)
        return build_empty_state()
    except json.JSONDecodeError:
        LOGGER.warning("State file at %s is invalid JSON. Falling back to default state.", state_path)
        return build_empty_state()

    state = build_empty_state()
    raw_source_pools = data.get("source_pools", {})
    for player_id in PLAYER_IDS:
        state["source_pools"][player_id] = _normalize_track_list(list(raw_source_pools.get(player_id, [])))
    raw_players = data.get("players", {})
    for player_id in PLAYER_IDS:
        raw_player = raw_players.get(player_id)
        if isinstance(raw_player, dict):
            state["players"][player_id]["name"] = raw_player.get("name") or _default_player_name(player_id)
            state["players"][player_id]["selection"] = _normalize_track_list(list(raw_player.get("selection", [])))
        elif isinstance(raw_player, list):
            state["players"][player_id]["selection"] = _normalize_track_list(list(raw_player))
    state["mix"] = _normalize_track_list(list(data.get("mix", [])))
    return state


def save_state(state_data: dict[str, Any], state_path: Path = STATE_FILE) -> None:
    state_path.write_text(
        json.dumps(state_data, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


class MixManager:
    def __init__(
        self,
        settings: Settings,
        deezer_client: DeezerClient,
        tracks_per_player: int = 20,
        randomizer: random.Random | None = None,
        state_path: Path = STATE_FILE,
    ) -> None:
        self.settings = settings
        self.deezer_client = deezer_client
        self.tracks_per_player = tracks_per_player
        self.randomizer = randomizer or random.Random()
        self.state_path = state_path
        self.state: dict[str, Any] = load_state(self.state_path)

    async def load_source_pools(self, force: bool = False) -> dict[str, list[dict[str, str]]]:
        if not force and all(self.state["source_pools"].values()):
            return self.state["source_pools"]

        source_pools: dict[str, list[dict[str, str]]] = {}
        for player_id, playlist_id in self.settings.source_playlists.items():
            playlist_data = await self.deezer_client.get_playlist_tracks(playlist_id)
            source_pools[player_id] = _deduplicate(list(playlist_data["tracks"]))
            if playlist_data["name"]:
                self.state["players"][player_id]["name"] = playlist_data["name"]

        self.state["source_pools"] = source_pools
        return source_pools

    def get_cached_source_pools(self) -> dict[str, list[dict[str, str]]]:
        source_pools = self.state["source_pools"]
        if not any(source_pools.values()):
            raise ValueError("Source playlists are not loaded. Use reset to populate the local cache first.")
        return source_pools

    async def ensure_state_loaded(self) -> None:
        if any(self.state["source_pools"].values()):
            return
        await self.reload_all_data()

    async def reload_all_data(self) -> dict[str, Any]:
        self.state = build_empty_state()
        await self.load_source_pools(force=True)
        save_state(self.state, self.state_path)
        return self._build_status_payload()

    async def refresh_player_source_cache(self, player_id: str) -> None:
        playlist_id = self.settings.source_playlists[player_id]
        playlist_data = await self.deezer_client.get_playlist_tracks(playlist_id)
        self.state["source_pools"][player_id] = _deduplicate(list(playlist_data["tracks"]))
        if playlist_data["name"]:
            self.state["players"][player_id]["name"] = playlist_data["name"]
        save_state(self.state, self.state_path)

    async def generate_mix(self, balanced: bool = False) -> dict[str, Any]:
        source_pools = self.get_cached_source_pools()
        selections = self._build_selections(source_pools, balanced=balanced)
        return await self._publish_mix(selections)

    async def refresh_player(self, player_id: str, balanced: bool = False) -> dict[str, Any]:
        if player_id not in PLAYER_IDS:
            raise ValueError(f"Unknown player_id: {player_id}")

        await self.refresh_player_source_cache(player_id)
        source_pools = self.get_cached_source_pools()
        if not balanced:
            selections = self._build_selections(source_pools, balanced=False)
            return await self._publish_mix(selections)

        if not any(self.state["players"][player_id]["selection"] for player_id in PLAYER_IDS):
            selections = self._build_selections(source_pools, balanced=True)
            return await self._publish_mix(selections)

        selections = {
            player_id: list(self.state["players"][player_id]["selection"])
            for player_id in PLAYER_IDS
        }

        desired_count = self._get_balanced_count(source_pools)
        if desired_count <= 0:
            selections[player_id] = []
            return await self._publish_mix(selections)

        current_selection = selections.get(player_id, [])
        current_selection_ids = {track["id"] for track in current_selection}
        available_tracks = [
            track
            for track_id in source_pools[player_id]
            for track in [track_id]
            if track["id"] not in current_selection_ids
        ]
        if len(available_tracks) < desired_count:
            available_tracks = list(source_pools[player_id])

        selections[player_id] = self.randomizer.sample(available_tracks, desired_count)
        return await self._publish_mix(selections)

    async def get_status(self) -> dict[str, Any]:
        if any(self.state["source_pools"].values()) and not self.state["mix"]:
            LOGGER.warning("Source pools are populated but mix is empty. Rebuilding mix from cached state.")
            return await self.generate_mix(balanced=False)
        return self._build_status_payload()

    def _build_status_payload(self) -> dict[str, Any]:
        return {
            "source_pools": self.state["source_pools"],
            "players": self.state["players"],
            "mix": self.state["mix"],
        }

    def _build_selections(
        self,
        source_pools: dict[str, list[dict[str, str]]],
        balanced: bool,
    ) -> dict[str, list[dict[str, str]]]:
        if not balanced:
            return {
                player_id: list(source_pools[player_id])
                for player_id in PLAYER_IDS
            }

        desired_count = self._get_balanced_count(source_pools)
        return {
            player_id: self.randomizer.sample(source_pools[player_id], desired_count)
            if desired_count > 0 else []
            for player_id in PLAYER_IDS
        }

    def _get_balanced_count(self, source_pools: dict[str, list[dict[str, str]]]) -> int:
        lengths = [len(source_pools[player_id]) for player_id in PLAYER_IDS]
        return min(lengths) if lengths else 0

    async def _publish_mix(self, selections: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
        mixed_tracks = [
            track
            for player_id in PLAYER_IDS
            for track in selections[player_id]
        ]
        self.randomizer.shuffle(mixed_tracks)
        final_track_ids = [track["id"] for track in mixed_tracks]
        await self.deezer_client.update_target_playlist(
            self.settings.target_playlist,
            final_track_ids,
        )
        for player_id in PLAYER_IDS:
            self.state["players"][player_id]["selection"] = list(selections[player_id])
        self.state["mix"] = mixed_tracks
        save_state(self.state, self.state_path)
        return self._build_status_payload()


def create_app(manager: MixManager | Any | None = None):
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    if manager is None:
        settings = Settings.from_env()
        manager = MixManager(
            settings=settings,
            deezer_client=DeezerClient(arl=settings.deezer_arl),
        )

    @asynccontextmanager
    async def lifespan(app: Any):
        if hasattr(app.state.manager, "ensure_state_loaded"):
            await app.state.manager.ensure_state_loaded()
        yield

    app = FastAPI(title="Deezer Mix & Refresh", lifespan=lifespan)
    app.state.manager = manager

    async def get_manager() -> Any:
        current_manager = app.state.manager
        if hasattr(current_manager, "ensure_state_loaded"):
            await current_manager.ensure_state_loaded()
        return current_manager

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        manager = await get_manager()
        return await manager.get_status()

    @app.post("/api/generate")
    async def generate_mix(balanced: bool = False) -> dict[str, Any]:
        try:
            manager = await get_manager()
            return await manager.generate_mix(balanced=balanced)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - external service errors
            LOGGER.exception("Unable to generate mix")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh/{player_id}")
    async def refresh_player(player_id: str, balanced: bool = False) -> dict[str, Any]:
        try:
            manager = await get_manager()
            return await manager.refresh_player(player_id, balanced=balanced)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - external service errors
            LOGGER.exception("Unable to refresh player selection")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/reset")
    async def reset_data() -> dict[str, Any]:
        try:
            manager = await get_manager()
            await manager.reload_all_data()
            return await manager.generate_mix()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - external service errors
            LOGGER.exception("Unable to reset data and regenerate mix")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


app = create_app() if __name__ != "__main__" else None
