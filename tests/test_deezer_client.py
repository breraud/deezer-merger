import unittest
from unittest.mock import AsyncMock, patch


class DeezerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_playlist_tracks_extracts_track_ids(self) -> None:
        from deezer_client import DeezerClient

        client = AsyncMock()
        client.get_playlist.return_value = {
            "tracks": {
                "edges": [
                    {"node": {"id": "11"}},
                    {"node": {"id": 22}},
                    {"node": {"SNG_ID": "33"}},
                ]
            }
        }

        service = DeezerClient(arl="token", client=client)

        track_ids = await service.get_playlist_tracks("123")

        self.assertEqual(track_ids, ["11", "22", "33"])
        client.get_playlist.assert_awaited_once_with(playlist_id="123")

    async def test_update_target_playlist_clears_then_readds_tracks_by_batches(self) -> None:
        from deezer_client import DeezerClient

        client = AsyncMock()
        client.get_playlist.return_value = {
            "tracks": {
                "edges": [
                    {"node": {"id": str(index)}} for index in range(1, 21)
                ]
            }
        }
        track_ids = [str(index) for index in range(1, 126)]

        service = DeezerClient(arl="token", client=client, batch_size=50, batch_delay=0.01)

        with patch("deezer_client.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            await service.update_target_playlist("999", track_ids)

        client.remove_tracks_from_playlist.assert_awaited_once_with(
            playlist_id="999",
            track_ids=[str(index) for index in range(1, 21)],
        )
        self.assertEqual(client.add_tracks_to_playlist.await_count, 3)
        client.add_tracks_to_playlist.assert_any_await(
            playlist_id="999",
            track_ids=[str(index) for index in range(1, 51)],
        )
        client.add_tracks_to_playlist.assert_any_await(
            playlist_id="999",
            track_ids=[str(index) for index in range(51, 101)],
        )
        client.add_tracks_to_playlist.assert_any_await(
            playlist_id="999",
            track_ids=[str(index) for index in range(101, 126)],
        )
        self.assertEqual(sleep_mock.await_count, 3)


if __name__ == "__main__":
    unittest.main()
