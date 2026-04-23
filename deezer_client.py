import asyncio
import logging
from collections.abc import Iterable
from typing import Any


LOGGER = logging.getLogger(__name__)


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return getattr(value, "__dict__", {})


def _extract_track_metadata(payload: Any) -> list[dict[str, str]]:
    data = _as_mapping(payload)
    tracks = _as_mapping(data.get("tracks"))
    edges = tracks.get("edges")

    if edges is None and isinstance(data.get("tracks"), list):
        edges = data["tracks"]

    if edges is None and isinstance(tracks.get("items"), list):
        edges = tracks["items"]

    track_data: list[dict[str, str]] = []
    for edge in edges or []:
        edge_data = _as_mapping(edge)
        node = _as_mapping(edge_data.get("node", edge_data))
        raw_track_id = node.get("id") or node.get("SNG_ID") or node.get("track_id")
        if raw_track_id is None:
            continue
        contributors = _as_mapping(node.get("contributors"))
        contributor_edges = contributors.get("edges") or []
        artist_name = ""
        for contributor_edge in contributor_edges:
            contributor_node = _as_mapping(_as_mapping(contributor_edge).get("node"))
            artist_name = contributor_node.get("name", "")
            if artist_name:
                break

        track_data.append(
            {
                "id": str(raw_track_id),
                "title": str(node.get("title") or ""),
                "artist": str(artist_name or ""),
            }
        )
    return track_data


def _extract_playlist_name(payload: Any) -> str:
    data = _as_mapping(payload)
    raw_name = (
        data.get("title")
        or data.get("name")
        or data.get("displayTitle")
        or data.get("display_title")
    )
    return str(raw_name) if raw_name else ""


def _extract_page_info(payload: Any) -> tuple[bool, str | None]:
    data = _as_mapping(payload)
    tracks = _as_mapping(data.get("tracks"))
    page_info = _as_mapping(tracks.get("pageInfo") or tracks.get("page_info"))
    has_next_page = bool(page_info.get("hasNextPage", page_info.get("has_next_page", False)))
    end_cursor = page_info.get("endCursor") or page_info.get("end_cursor")
    return has_next_page, end_cursor


class DeezerClient:
    def __init__(
        self,
        arl: str,
        client: Any | None = None,
        batch_size: int = 50,
        batch_delay: float = 0.3,
    ) -> None:
        if not arl:
            raise ValueError("DEEZER_ARL is required")
        self.arl = arl
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from deezer_python_gql import DeezerGQLClient

            self._client = DeezerGQLClient(arl=self.arl)
        return self._client

    async def get_playlist_tracks(self, playlist_id: str) -> dict[str, Any]:
        track_data: list[dict[str, str]] = []
        next_cursor: str | None = None
        playlist_name = ""

        while True:
            request_kwargs: dict[str, Any] = {
                "playlist_id": str(playlist_id),
                "tracks_first": self.batch_size,
            }
            if next_cursor:
                request_kwargs["tracks_after"] = next_cursor

            try:
                playlist = await self.client.get_playlist(**request_kwargs)
            except Exception:
                LOGGER.exception("Unable to fetch playlist %s", playlist_id)
                return {"name": "", "tracks": []}

            if playlist is None:
                LOGGER.error("Playlist %s was not found or is not accessible", playlist_id)
                return {"name": "", "tracks": []}

            playlist_name = playlist_name or _extract_playlist_name(playlist)
            track_data.extend(_extract_track_metadata(playlist))
            has_next_page, next_cursor = _extract_page_info(playlist)
            if not has_next_page or not next_cursor:
                break

        LOGGER.info("Fetched %s tracks from playlist %s", len(track_data), playlist_id)
        return {"name": playlist_name, "tracks": track_data}

    async def update_target_playlist(self, playlist_id: str, track_ids: Iterable[str]) -> None:
        normalized_track_ids = [str(track_id) for track_id in track_ids]
        existing_playlist = await self.get_playlist_tracks(playlist_id)
        existing_track_ids = [track["id"] for track in existing_playlist["tracks"]]

        if existing_track_ids:
            LOGGER.info(
                "Removing %s existing tracks from playlist %s",
                len(existing_track_ids),
                playlist_id,
            )
            await self.client.remove_tracks_from_playlist(
                playlist_id=str(playlist_id),
                track_ids=existing_track_ids,
            )

        for batch in _chunked(normalized_track_ids, self.batch_size):
            LOGGER.info(
                "Adding batch of %s tracks to playlist %s",
                len(batch),
                playlist_id,
            )
            await self.client.add_tracks_to_playlist(
                playlist_id=str(playlist_id),
                track_ids=batch,
            )
            await asyncio.sleep(self.batch_delay)
