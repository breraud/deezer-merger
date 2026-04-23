import unittest
from unittest.mock import AsyncMock, patch


class DeezerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_playlist_tracks_extracts_name_and_track_ids_across_pages(self) -> None:
        from deezer_client import DeezerClient

        client = AsyncMock()
        client.get_playlist.side_effect = [
            {
                "title": "Road Trip",
                "tracks": {
                    "edges": [
                        {"cursor": "c1", "node": {"id": "11"}},
                        {"cursor": "c2", "node": {"id": 22}},
                    ],
                    "pageInfo": {"hasNextPage": True, "endCursor": "c2"},
                }
            },
            {
                "title": "Road Trip",
                "tracks": {
                    "edges": [
                        {"cursor": "c3", "node": {"SNG_ID": "33"}},
                        {"cursor": "c4", "node": {"id": "44"}},
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": "c4"},
                }
            }
        ]

        service = DeezerClient(arl="token", client=client)

        playlist_data = await service.get_playlist_tracks("123")

        self.assertEqual(playlist_data["name"], "Road Trip")
        self.assertEqual(playlist_data["track_ids"], ["11", "22", "33", "44"])
        self.assertEqual(client.get_playlist.await_count, 2)
        client.get_playlist.assert_any_await(playlist_id="123", tracks_first=50)
        client.get_playlist.assert_any_await(playlist_id="123", tracks_first=50, tracks_after="c2")

    async def test_get_playlist_tracks_returns_empty_list_when_playlist_is_missing(self) -> None:
        from deezer_client import DeezerClient

        client = AsyncMock()
        client.get_playlist.return_value = None

        service = DeezerClient(arl="token", client=client)

        with self.assertLogs("deezer_client", level="ERROR") as logs:
            playlist_data = await service.get_playlist_tracks("404")

        self.assertEqual(playlist_data, {"name": "", "track_ids": []})
        self.assertIn("404", logs.output[0])

    async def test_get_playlist_tracks_returns_empty_list_when_playlist_fetch_raises(self) -> None:
        from deezer_client import DeezerClient

        client = AsyncMock()
        client.get_playlist.side_effect = RuntimeError("playlist is private")

        service = DeezerClient(arl="token", client=client)

        with self.assertLogs("deezer_client", level="ERROR") as logs:
            playlist_data = await service.get_playlist_tracks("private")

        self.assertEqual(playlist_data, {"name": "", "track_ids": []})
        self.assertIn("private", logs.output[0])

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
