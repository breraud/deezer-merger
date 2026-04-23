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
    async def test_generate_mix_full_merge_uses_entire_cached_pools(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
            )
            manager.state["source_pools"] = {
                "player1": ["1", "2", "3"],
                "player2": ["4", "5"],
                "player3": ["6", "7", "8", "9"],
            }

            payload = await manager.generate_mix(balanced=False)

        self.assertEqual(payload["players"]["player1"], ["1", "2", "3"])
        self.assertEqual(payload["players"]["player2"], ["4", "5"])
        self.assertEqual(payload["players"]["player3"], ["6", "7", "8", "9"])
        self.assertEqual(len(payload["mix"]), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", payload["mix"])

    async def test_generate_mix_balanced_samples_using_smallest_playlist_size(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            class Randomizer:
                def __init__(self):
                    self.sample_call_count = 0

                def sample(self, pool, count):
                    self.sample_call_count += 1
                    return list(pool)[:count]

                def shuffle(self, _items):
                    return None

            randomizer = Randomizer()
            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
                randomizer=randomizer,
            )
            manager.state["source_pools"] = {
                "player1": ["1", "2", "3"],
                "player2": ["4", "5"],
                "player3": ["6", "7", "8", "9"],
            }

            payload = await manager.generate_mix(balanced=True)

        self.assertEqual(payload["players"]["player1"], ["1", "2"])
        self.assertEqual(payload["players"]["player2"], ["4", "5"])
        self.assertEqual(payload["players"]["player3"], ["6", "7"])
        self.assertEqual(len(payload["mix"]), 6)
        self.assertEqual(randomizer.sample_call_count, 3)

    async def test_reload_all_data_resets_state_and_reloads_source_pools(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            deezer_client.get_playlist_tracks.side_effect = [
                ["11", "12"],
                ["21", "22", "22"],
                [],
            ]

            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
            )
            manager.state["source_pools"] = {"player1": ["old"], "player2": ["old"], "player3": ["old"]}
            manager.state["players"] = {"player1": ["x"], "player2": ["y"], "player3": ["z"]}
            manager.state["mix"] = ["x", "y", "z"]

            payload = await manager.reload_all_data()

        self.assertEqual(payload["source_pools"]["player1"], ["11", "12"])
        self.assertEqual(payload["source_pools"]["player2"], ["21", "22"])
        self.assertEqual(payload["source_pools"]["player3"], [])
        self.assertEqual(payload["players"], {"player1": [], "player2": [], "player3": []})
        self.assertEqual(payload["mix"], [])

    async def test_generate_mix_balanced_reuses_smallest_pool_size_after_cache_load(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            deezer_client.get_playlist_tracks.side_effect = [
                ["1", "2", "3", "4"],
                ["5", "6", "7"],
                ["8", "9", "10", "11", "12"],
            ]
            class Randomizer:
                def sample(self, pool, count):
                    return list(pool)[:count]

                def shuffle(self, _items):
                    return None

            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
                randomizer=Randomizer(),
            )

            payload = await manager.generate_mix(balanced=True)

        self.assertEqual(set(payload["players"]), {"player1", "player2", "player3"})
        self.assertEqual(payload["players"]["player1"], ["1", "2", "3"])
        self.assertEqual(payload["players"]["player2"], ["5", "6", "7"])
        self.assertEqual(payload["players"]["player3"], ["8", "9", "10"])
        self.assertEqual(len(payload["mix"]), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", payload["mix"])

    async def test_refresh_player_replaces_only_targeted_selection_in_balanced_mode(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            class Randomizer:
                def sample(self, pool, count):
                    return list(pool)[-count:]

                def shuffle(self, _items):
                    return None

            randomizer = Randomizer()
            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
                randomizer=randomizer,
            )
            manager.state["source_pools"] = {
                "player1": ["1", "2", "10", "11", "14"],
                "player2": ["3", "4", "12"],
                "player3": ["5", "6", "13"],
            }
            manager.state["players"] = {
                "player1": ["1", "2", "10"],
                "player2": ["3", "4", "12"],
                "player3": ["5", "6", "13"],
            }
            manager.state["mix"] = ["1", "2", "10", "3", "4", "12", "5", "6", "13"]

            payload = await manager.refresh_player("player1", balanced=True)

        self.assertEqual(payload["players"]["player2"], ["3", "4", "12"])
        self.assertEqual(payload["players"]["player3"], ["5", "6", "13"])
        self.assertEqual(payload["players"]["player1"], ["10", "11", "14"])
        self.assertEqual(len(set(payload["mix"])), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", payload["mix"])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints_return_status_payload(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            import httpx
            from main import create_app

            class FakeManager:
                def __init__(self):
                    self.source_pools = {}
                    self.generate_balanced = None
                    self.refresh_balanced = None

                async def get_status(self):
                    return {"mix": [], "players": {}, "source_pools": self.source_pools}

                async def generate_mix(self, balanced: bool = False):
                    self.generate_balanced = balanced
                    return {
                        "mix": ["1"],
                        "players": {"player1": ["1"], "player2": [], "player3": []},
                        "source_pools": self.source_pools,
                    }

                async def refresh_player(self, _player_id: str, balanced: bool = False):
                    self.refresh_balanced = balanced
                    return {"mix": ["2"], "players": {"player2": ["2"]}}

                async def reload_all_data(self):
                    self.source_pools = {"player1": ["1"], "player2": [], "player3": []}
                    return {"mix": [], "players": {}, "source_pools": self.source_pools}

            manager = FakeManager()
            transport = httpx.ASGITransport(app=create_app(manager=manager))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/status")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], [])

                response = await client.post("/api/generate?balanced=true")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], ["1"])
                self.assertTrue(manager.generate_balanced)

                response = await client.post("/api/refresh/player2?balanced=false")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], ["2"])
                self.assertFalse(manager.refresh_balanced)

                response = await client.post("/api/reset")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["source_pools"]["player1"], ["1"])


if __name__ == "__main__":
    unittest.main()
