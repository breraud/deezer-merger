import os
import unittest
from unittest.mock import AsyncMock, patch


ENV = {
    "DEEZER_ARL": "arl-token",
    "PLAYLIST_SOURCE_1": "101",
    "PLAYLIST_SOURCE_2": "202",
    "PLAYLIST_SOURCE_3": "303",
    "PLAYLIST_CIBLE": "999",
}


class MainTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_mix_builds_unique_selection_and_updates_target(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            deezer_client.get_playlist_tracks.side_effect = [
                ["1", "2", "3", "4"],
                ["3", "4", "5", "6"],
                ["6", "7", "8", "9"],
            ]

            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
            )

            payload = await manager.generate_mix()

        self.assertEqual(set(payload["players"]), {"player1", "player2", "player3"})
        self.assertEqual(len(payload["players"]["player1"]), 2)
        self.assertEqual(len(payload["players"]["player2"]), 2)
        self.assertEqual(len(payload["players"]["player3"]), 2)
        self.assertEqual(len(payload["mix"]), 6)
        self.assertEqual(len(set(payload["mix"])), 6)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", payload["mix"])

    async def test_refresh_player_replaces_only_targeted_selection(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
            )
            manager.state["source_pools"] = {
                "player1": ["1", "2", "10", "11"],
                "player2": ["3", "4", "12"],
                "player3": ["5", "6", "13"],
            }
            manager.state["players"] = {
                "player1": ["1", "2"],
                "player2": ["3", "4"],
                "player3": ["5", "6"],
            }
            manager.state["mix"] = ["1", "2", "3", "4", "5", "6"]

            payload = await manager.refresh_player("player1")

        self.assertEqual(payload["players"]["player2"], ["3", "4"])
        self.assertEqual(payload["players"]["player3"], ["5", "6"])
        self.assertEqual(payload["players"]["player1"], ["10", "11"])
        self.assertEqual(len(set(payload["mix"])), 6)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", payload["mix"])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints_return_status_payload(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            import httpx
            from main import create_app

            class FakeManager:
                async def get_status(self):
                    return {"mix": [], "players": {}, "source_pools": {}}

                async def generate_mix(self):
                    return {"mix": ["1"], "players": {"player1": ["1"]}}

                async def refresh_player(self, _player_id: str):
                    return {"mix": ["2"], "players": {"player2": ["2"]}}

            transport = httpx.ASGITransport(app=create_app(manager=FakeManager()))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/status")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], [])

                response = await client.post("/api/generate")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], ["1"])

                response = await client.post("/api/refresh/player2")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], ["2"])


if __name__ == "__main__":
    unittest.main()
