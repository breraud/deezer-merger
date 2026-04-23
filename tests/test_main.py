import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ENV = {
    "DEEZER_ARL": "arl-token",
    "PLAYLIST_SOURCE_1": "101",
    "PLAYLIST_SOURCE_2": "202",
    "PLAYLIST_SOURCE_3": "303",
    "PLAYLIST_CIBLE": "999",
}


class MainTests(unittest.IsolatedAsyncioTestCase):
    def make_track(self, track_id: str, title: str | None = None, artist: str = "Artist") -> dict[str, str]:
        return {
            "id": track_id,
            "title": title or f"Track {track_id}",
            "artist": artist,
        }

    async def test_load_state_returns_empty_structure_when_file_is_missing(self) -> None:
        from main import load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            state = load_state(Path(tmpdir) / "state.json")

        self.assertEqual(
            state,
            {
                "source_pools": {"player1": [], "player2": [], "player3": []},
                "players": {
                    "player1": {"name": "Joueur 1", "selection": []},
                    "player2": {"name": "Joueur 2", "selection": []},
                    "player3": {"name": "Joueur 3", "selection": []},
                },
                "mix": [],
            },
        )

    async def test_save_state_and_load_state_round_trip_json_file(self) -> None:
        from main import load_state, save_state

        payload = {
            "source_pools": {
                "player1": [self.make_track("1")],
                "player2": [self.make_track("2")],
                "player3": [],
            },
            "players": {
                "player1": {"name": "Playlist 1", "selection": [self.make_track("1")]},
                "player2": {"name": "Playlist 2", "selection": []},
                "player3": {"name": "Playlist 3", "selection": []},
            },
            "mix": [self.make_track("1"), self.make_track("2")],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            save_state(payload, state_path)
            loaded_state = load_state(state_path)

        self.assertEqual(loaded_state, payload)

    async def test_generate_mix_persists_updated_state_to_local_json_file(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                state_path = Path(tmpdir) / "state.json"
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    tracks_per_player=2,
                    state_path=state_path,
                )
                manager.state["source_pools"] = {
                    "player1": [self.make_track("1"), self.make_track("2"), self.make_track("3")],
                    "player2": [self.make_track("4"), self.make_track("5")],
                    "player3": [self.make_track("6"), self.make_track("7"), self.make_track("8"), self.make_track("9")],
                }
                manager.state["players"]["player1"]["name"] = "Playlist 1"
                manager.state["players"]["player2"]["name"] = "Playlist 2"
                manager.state["players"]["player3"]["name"] = "Playlist 3"
                payload = await manager.generate_mix(balanced=False)
                saved_state = state_path.read_text(encoding="utf-8")

        self.assertIn("\"mix\"", saved_state)
        self.assertEqual(payload["mix"], manager.state["mix"])

    async def test_generate_mix_uses_only_cached_state_without_refetching_sources(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    state_path=Path(tmpdir) / "state.json",
                )
                manager.state["source_pools"] = {
                    "player1": [self.make_track("1")],
                    "player2": [self.make_track("2")],
                    "player3": [self.make_track("3")],
                }

                payload = await manager.generate_mix(balanced=False)

        self.assertEqual(sorted(track["id"] for track in payload["mix"]), ["1", "2", "3"])
        deezer_client.get_playlist_tracks.assert_not_awaited()

    async def test_generate_mix_fails_when_cache_is_empty_instead_of_refetching(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    state_path=Path(tmpdir) / "state.json",
                )

                with self.assertRaises(ValueError):
                    await manager.generate_mix(balanced=False)

        deezer_client.get_playlist_tracks.assert_not_awaited()

    async def test_refresh_player_uses_only_cached_state_without_refetching_sources(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    state_path=Path(tmpdir) / "state.json",
                )
                manager.state["source_pools"] = {
                    "player1": [self.make_track("1"), self.make_track("10")],
                    "player2": [self.make_track("2")],
                    "player3": [self.make_track("3")],
                }
                manager.state["players"] = {
                    "player1": {"name": "Alpha", "selection": [self.make_track("1")]},
                    "player2": {"name": "Beta", "selection": [self.make_track("2")]},
                    "player3": {"name": "Gamma", "selection": [self.make_track("3")]},
                }
                manager.state["mix"] = [self.make_track("1"), self.make_track("2"), self.make_track("3")]

                await manager.refresh_player("player1", balanced=False)

        deezer_client.get_playlist_tracks.assert_not_awaited()

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
                "player1": [self.make_track("1"), self.make_track("2"), self.make_track("3")],
                "player2": [self.make_track("4"), self.make_track("5")],
                "player3": [self.make_track("6"), self.make_track("7"), self.make_track("8"), self.make_track("9")],
            }

            payload = await manager.generate_mix(balanced=False)

        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["1", "2", "3"])
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["4", "5"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["6", "7", "8", "9"])
        self.assertEqual(len(payload["mix"]), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])

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
                "player1": [self.make_track("1"), self.make_track("2"), self.make_track("3")],
                "player2": [self.make_track("4"), self.make_track("5")],
                "player3": [self.make_track("6"), self.make_track("7"), self.make_track("8"), self.make_track("9")],
            }

            payload = await manager.generate_mix(balanced=True)

        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["1", "2"])
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["4", "5"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["6", "7"])
        self.assertEqual(len(payload["mix"]), 6)
        self.assertEqual(randomizer.sample_call_count, 3)

    async def test_reload_all_data_resets_state_and_reloads_source_pools(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            deezer_client.get_playlist_tracks.side_effect = [
                {"name": "Alpha", "tracks": [self.make_track("11"), self.make_track("12")]},
                {"name": "Beta", "tracks": [self.make_track("21"), self.make_track("22"), self.make_track("22")]},
                {"name": "Gamma", "tracks": []},
            ]

            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
                tracks_per_player=2,
            )
            manager.state["source_pools"] = {
                "player1": [self.make_track("old1")],
                "player2": [self.make_track("old2")],
                "player3": [self.make_track("old3")],
            }
            manager.state["players"] = {
                "player1": {"name": "Old 1", "selection": [self.make_track("x")]},
                "player2": {"name": "Old 2", "selection": [self.make_track("y")]},
                "player3": {"name": "Old 3", "selection": [self.make_track("z")]},
            }
            manager.state["mix"] = [self.make_track("x"), self.make_track("y"), self.make_track("z")]

            payload = await manager.reload_all_data()

        self.assertEqual([track["id"] for track in payload["source_pools"]["player1"]], ["11", "12"])
        self.assertEqual([track["id"] for track in payload["source_pools"]["player2"]], ["21", "22"])
        self.assertEqual(payload["source_pools"]["player3"], [])
        self.assertEqual(payload["players"]["player1"], {"name": "Alpha", "selection": []})
        self.assertEqual(payload["players"]["player2"], {"name": "Beta", "selection": []})
        self.assertEqual(payload["players"]["player3"], {"name": "Gamma", "selection": []})
        self.assertEqual(payload["mix"], [])

    async def test_generate_mix_balanced_reuses_smallest_pool_size_after_reload_cache(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            deezer_client.get_playlist_tracks.side_effect = [
                {"name": "Alpha", "tracks": [self.make_track("1"), self.make_track("2"), self.make_track("3"), self.make_track("4")]},
                {"name": "Beta", "tracks": [self.make_track("5"), self.make_track("6"), self.make_track("7")]},
                {"name": "Gamma", "tracks": [self.make_track("8"), self.make_track("9"), self.make_track("10"), self.make_track("11"), self.make_track("12")]},
            ]
            class Randomizer:
                def sample(self, pool, count):
                    return list(pool)[:count]

                def shuffle(self, _items):
                    return None

            with tempfile.TemporaryDirectory() as tmpdir:
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    tracks_per_player=2,
                    randomizer=Randomizer(),
                    state_path=Path(tmpdir) / "state.json",
                )
                await manager.reload_all_data()
                payload = await manager.generate_mix(balanced=True)

        self.assertEqual(set(payload["players"]), {"player1", "player2", "player3"})
        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["1", "2", "3"])
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["5", "6", "7"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["8", "9", "10"])
        self.assertEqual(len(payload["mix"]), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])

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
                "player1": [self.make_track("1"), self.make_track("2"), self.make_track("10"), self.make_track("11"), self.make_track("14")],
                "player2": [self.make_track("3"), self.make_track("4"), self.make_track("12")],
                "player3": [self.make_track("5"), self.make_track("6"), self.make_track("13")],
            }
            manager.state["players"] = {
                "player1": {"name": "Alpha", "selection": [self.make_track("1"), self.make_track("2"), self.make_track("10")]},
                "player2": {"name": "Beta", "selection": [self.make_track("3"), self.make_track("4"), self.make_track("12")]},
                "player3": {"name": "Gamma", "selection": [self.make_track("5"), self.make_track("6"), self.make_track("13")]},
            }
            manager.state["mix"] = [
                self.make_track("1"), self.make_track("2"), self.make_track("10"),
                self.make_track("3"), self.make_track("4"), self.make_track("12"),
                self.make_track("5"), self.make_track("6"), self.make_track("13"),
            ]

            payload = await manager.refresh_player("player1", balanced=True)

        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["3", "4", "12"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["5", "6", "13"])
        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["10", "11", "14"])
        self.assertEqual(len({track["id"] for track in payload["mix"]}), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])


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
                    return {
                        "mix": [],
                        "players": {
                            "player1": {"name": "Alpha", "selection": []},
                            "player2": {"name": "Beta", "selection": []},
                            "player3": {"name": "Gamma", "selection": []},
                        },
                        "source_pools": self.source_pools,
                    }

                async def generate_mix(self, balanced: bool = False):
                    self.generate_balanced = balanced
                    return {
                        "mix": [MainTests.make_track(self, "1", artist="Alpha")],
                        "players": {
                            "player1": {"name": "Alpha", "selection": [MainTests.make_track(self, "1", artist="Alpha")]},
                            "player2": {"name": "Beta", "selection": []},
                            "player3": {"name": "Gamma", "selection": []},
                        },
                        "source_pools": self.source_pools,
                    }

                async def refresh_player(self, _player_id: str, balanced: bool = False):
                    self.refresh_balanced = balanced
                    return {
                        "mix": [MainTests.make_track(self, "2", artist="Beta")],
                        "players": {
                            "player1": {"name": "Alpha", "selection": []},
                            "player2": {"name": "Beta", "selection": [MainTests.make_track(self, "2", artist="Beta")]},
                            "player3": {"name": "Gamma", "selection": []},
                        },
                        "source_pools": self.source_pools,
                    }

                async def reload_all_data(self):
                    self.source_pools = {"player1": ["1"], "player2": [], "player3": []}
                    return {
                        "mix": [],
                        "players": {
                            "player1": {"name": "Alpha", "selection": []},
                            "player2": {"name": "Beta", "selection": []},
                            "player3": {"name": "Gamma", "selection": []},
                        },
                        "source_pools": self.source_pools,
                    }

            manager = FakeManager()
            transport = httpx.ASGITransport(app=create_app(manager=manager))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/api/status")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"], [])

                response = await client.post("/api/generate?balanced=true")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"][0]["id"], "1")
                self.assertTrue(manager.generate_balanced)

                response = await client.post("/api/refresh/player2?balanced=false")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mix"][0]["id"], "2")
                self.assertFalse(manager.refresh_balanced)

                response = await client.post("/api/reset")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["source_pools"]["player1"], ["1"])


if __name__ == "__main__":
    unittest.main()
