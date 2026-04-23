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


def _extract_track_ids(payload: Any) -> list[str]:
    data = _as_mapping(payload)
    tracks = _as_mapping(data.get("tracks"))
    edges = tracks.get("edges")

    if edges is None and isinstance(data.get("tracks"), list):
        edges = data["tracks"]

    if edges is None and isinstance(tracks.get("items"), list):
        edges = tracks["items"]

    track_ids: list[str] = []
    for edge in edges or []:
        edge_data = _as_mapping(edge)
        node = _as_mapping(edge_data.get("node", edge_data))
        raw_track_id = node.get("id") or node.get("SNG_ID") or node.get("track_id")
        if raw_track_id is None:
            continue
        track_ids.append(str(raw_track_id))
    return track_ids


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

    async def get_playlist_tracks(self, playlist_id: str) -> list[str]:
        playlist = await self.client.get_playlist(playlist_id=str(playlist_id))
        track_ids = _extract_track_ids(playlist)
        LOGGER.info("Fetched %s tracks from playlist %s", len(track_ids), playlist_id)
        return track_ids

    async def update_target_playlist(self, playlist_id: str, track_ids: Iterable[str]) -> None:
        normalized_track_ids = [str(track_id) for track_id in track_ids]
        existing_track_ids = await self.get_playlist_tracks(playlist_id)

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
