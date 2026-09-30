import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


APP_PASSWORD = "mot-de-passe-test"

ENV = {
    "DEEZER_ARL": "arl-token",
    "PLAYLIST_SOURCE_1": "101",
    "PLAYLIST_SOURCE_2": "202",
    "PLAYLIST_SOURCE_3": "303",
    "PLAYLIST_CIBLE": "999",
    "APP_PASSWORD": APP_PASSWORD,
}


def make_client(app):
    import httpx

    # https : le cookie de session est Secure, httpx ne le renverrait pas en http.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver")


async def login(client) -> None:
    response = await client.post("/login", data={"password": APP_PASSWORD})
    assert response.status_code == 303, response.status_code


class MainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._state_dir = tempfile.TemporaryDirectory()
        self.test_state_path = Path(self._state_dir.name) / "test_state.json"
        self.env = {
            **ENV,
            "STATE_FILE_PATH": str(self.test_state_path),
        }

    def tearDown(self) -> None:
        self._state_dir.cleanup()

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

    async def test_load_state_returns_empty_structure_when_file_is_empty(self) -> None:
        from main import load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state_path.write_text("", encoding="utf-8")
            state = load_state(state_path)

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

    async def test_load_state_returns_empty_structure_when_file_contains_invalid_json(self) -> None:
        from main import load_state

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state_path.write_text("{invalid", encoding="utf-8")
            state = load_state(state_path)

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

    async def test_mix_manager_uses_state_file_path_from_environment_by_default(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            manager = MixManager(
                settings=Settings.from_env(),
                deezer_client=deezer_client,
            )
            manager.state["source_pools"] = {
                "player1": [self.make_track("1")],
                "player2": [self.make_track("2")],
                "player3": [self.make_track("3")],
            }

            await manager.generate_mix(balanced=False)

        self.assertEqual(manager.state_path, self.test_state_path)
        self.assertTrue(self.test_state_path.exists())

    async def test_generate_mix_persists_updated_state_to_local_json_file(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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
        with patch.dict(os.environ, self.env, clear=True):
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

    async def test_get_status_rebuilds_mix_when_source_pools_exist_but_mix_is_empty(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            with tempfile.TemporaryDirectory() as tmpdir:
                manager = MixManager(
                    settings=Settings.from_env(),
                    deezer_client=deezer_client,
                    state_path=Path(tmpdir) / "state.json",
                )
                manager.state["source_pools"] = {
                    "player1": [self.make_track("1"), self.make_track("2")],
                    "player2": [self.make_track("3")],
                    "player3": [self.make_track("4"), self.make_track("5")],
                }
                manager.state["players"] = {
                    "player1": {"name": "Alpha", "selection": []},
                    "player2": {"name": "Beta", "selection": []},
                    "player3": {"name": "Gamma", "selection": []},
                }
                manager.state["mix"] = []

                payload = await manager.get_status()

        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["1", "2"])
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["3"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["4", "5"])
        self.assertEqual(len(payload["mix"]), 5)
        deezer_client.get_playlist_tracks.assert_not_awaited()
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])

    async def test_generate_mix_fails_when_cache_is_empty_instead_of_refetching(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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

    async def test_refresh_player_fetches_fresh_data_for_targeted_playlist_only(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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
                deezer_client.get_playlist_tracks.return_value = {
                    "name": "Alpha Fresh",
                    "tracks": [self.make_track("1"), self.make_track("10"), self.make_track("11")],
                }

                payload = await manager.refresh_player("player1", balanced=False)

        deezer_client.get_playlist_tracks.assert_awaited_once_with("101")
        self.assertEqual(payload["players"]["player1"]["name"], "Alpha Fresh")
        self.assertEqual([track["id"] for track in payload["source_pools"]["player1"]], ["1", "10", "11"])
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])

    async def test_generate_mix_full_merge_uses_entire_cached_pools(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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

    async def test_generate_mix_publishes_a_track_shared_by_two_playlists_only_once(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import MixManager, Settings

            deezer_client = AsyncMock()
            manager = MixManager(settings=Settings.from_env(), deezer_client=deezer_client)
            manager.state["source_pools"] = {
                "player1": [self.make_track("1"), self.make_track("2")],
                "player2": [self.make_track("2"), self.make_track("3")],
                "player3": [self.make_track("4")],
            }

            payload = await manager.generate_mix(balanced=False)

        published_ids = [track["id"] for track in payload["mix"]]
        self.assertEqual(sorted(published_ids), ["1", "2", "3", "4"])
        deezer_client.update_target_playlist.assert_awaited_once_with("999", published_ids)
        # Chaque playlist garde le titre partage dans sa selection.
        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["1", "2"])
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["2", "3"])

    async def test_status_payload_lists_tracks_shared_by_several_playlists(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import MixManager, Settings

            manager = MixManager(settings=Settings.from_env(), deezer_client=AsyncMock())
            manager.state["source_pools"] = {
                "player1": [self.make_track("1"), self.make_track("2"), self.make_track("5")],
                "player2": [self.make_track("5"), self.make_track("2"), self.make_track("3")],
                "player3": [self.make_track("4"), self.make_track("5")],
            }

            payload = await manager.generate_mix(balanced=False)

        # Dans l'ordre de premiere apparition, playlists dans l'ordre des joueurs.
        self.assertEqual(
            payload["duplicates"],
            [
                {**self.make_track("2"), "players": ["player1", "player2"]},
                {**self.make_track("5"), "players": ["player1", "player2", "player3"]},
            ],
        )

    async def test_status_payload_has_no_duplicates_when_playlists_do_not_overlap(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import MixManager, Settings

            manager = MixManager(settings=Settings.from_env(), deezer_client=AsyncMock())
            manager.state["source_pools"] = {
                "player1": [self.make_track("1")],
                "player2": [self.make_track("2")],
                "player3": [self.make_track("3")],
            }

            payload = await manager.generate_mix(balanced=False)

        self.assertEqual(payload["duplicates"], [])

    async def test_generate_mix_balanced_samples_using_smallest_playlist_size(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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
        with patch.dict(os.environ, self.env, clear=True):
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
        with patch.dict(os.environ, self.env, clear=True):
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
        with patch.dict(os.environ, self.env, clear=True):
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
            deezer_client.get_playlist_tracks.return_value = {
                "name": "Alpha Fresh",
                "tracks": [
                    self.make_track("1"),
                    self.make_track("2"),
                    self.make_track("10"),
                    self.make_track("11"),
                    self.make_track("14"),
                ],
            }

            payload = await manager.refresh_player("player1", balanced=True)

        deezer_client.get_playlist_tracks.assert_awaited_once_with("101")
        self.assertEqual(payload["players"]["player1"]["name"], "Alpha Fresh")
        self.assertEqual([track["id"] for track in payload["players"]["player2"]["selection"]], ["3", "4", "12"])
        self.assertEqual([track["id"] for track in payload["players"]["player3"]["selection"]], ["5", "6", "13"])
        self.assertEqual([track["id"] for track in payload["players"]["player1"]["selection"]], ["10", "11", "14"])
        self.assertEqual(len({track["id"] for track in payload["mix"]}), 9)
        deezer_client.update_target_playlist.assert_awaited_once_with("999", [track["id"] for track in payload["mix"]])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._state_dir = tempfile.TemporaryDirectory()
        self.test_state_path = Path(self._state_dir.name) / "test_state.json"
        self.env = {
            **ENV,
            "STATE_FILE_PATH": str(self.test_state_path),
        }

    def tearDown(self) -> None:
        self._state_dir.cleanup()

    async def test_app_auto_loads_deezer_data_when_state_is_empty(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            from main import create_app

            class FakeManager:
                def __init__(self):
                    self.ensure_called = False
                    self.state = {
                        "mix": [],
                        "players": {
                            "player1": {"name": "Alpha", "selection": []},
                            "player2": {"name": "Beta", "selection": []},
                            "player3": {"name": "Gamma", "selection": []},
                        },
                        "source_pools": {"player1": [], "player2": [], "player3": []},
                    }

                async def ensure_state_loaded(self):
                    self.ensure_called = True
                    self.state["source_pools"]["player1"] = [MainTests.make_track(self, "1", artist="Alpha")]

                async def get_status(self):
                    return self.state

                async def generate_mix(self, balanced: bool = False):
                    return self.state

                async def refresh_player(self, _player_id: str, balanced: bool = False):
                    return self.state

                async def reload_all_data(self):
                    return self.state

            manager = FakeManager()
            async with make_client(create_app(manager=manager, app_password=APP_PASSWORD)) as client:
                await login(client)
                response = await client.get("/api/status")

        self.assertTrue(manager.ensure_called)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_pools"]["player1"][0]["id"], "1")

    async def test_endpoints_return_status_payload(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
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
            async with make_client(create_app(manager=manager, app_password=APP_PASSWORD)) as client:
                await login(client)
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


class StatusOnlyManager:
    """Manager minimal : ces tests ne portent que sur l'acces aux routes."""

    def __init__(self) -> None:
        self.status_calls = 0
        self.generate_calls = 0

    async def get_status(self):
        self.status_calls += 1
        return {"mix": [], "players": {}, "source_pools": {}}

    async def generate_mix(self, balanced: bool = False):
        self.generate_calls += 1
        return {"mix": [], "players": {}, "source_pools": {}}


class AuthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # main execute create_app() a l'import : il lui faut un environnement complet.
        with patch.dict(os.environ, ENV, clear=True):
            import main
        self.main = main
        self.manager = StatusOnlyManager()

    def client(self, password: str = APP_PASSWORD):
        return make_client(self.main.create_app(manager=self.manager, app_password=password))

    async def test_settings_require_app_password(self) -> None:
        env = {key: value for key, value in ENV.items() if key != "APP_PASSWORD"}
        # Sans ce patch, un APP_PASSWORD du .env local ferait passer le test.
        with patch.dict(os.environ, env, clear=True), patch.object(self.main, "load_dotenv"):
            with self.assertRaisesRegex(ValueError, "APP_PASSWORD"):
                self.main.Settings.from_env()

    async def test_settings_read_app_password(self) -> None:
        with patch.dict(os.environ, ENV, clear=True):
            settings = self.main.Settings.from_env()

        self.assertEqual(settings.app_password, APP_PASSWORD)

    async def test_create_app_refuses_an_empty_password(self) -> None:
        with self.assertRaisesRegex(ValueError, "APP_PASSWORD"):
            self.main.create_app(manager=self.manager, app_password="")

    async def test_index_redirects_to_login_without_session(self) -> None:
        async with self.client() as client:
            response = await client.get("/")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    async def test_api_rejects_requests_without_session(self) -> None:
        async with self.client() as client:
            status = await client.get("/api/status")
            generate = await client.post("/api/generate")

        self.assertEqual(status.status_code, 401)
        self.assertEqual(generate.status_code, 401)
        self.assertEqual(self.manager.status_calls, 0)
        self.assertEqual(self.manager.generate_calls, 0)

    async def test_login_page_and_static_assets_are_public(self) -> None:
        async with self.client() as client:
            page = await client.get("/login")
            stylesheet = await client.get("/static/style.css")

        self.assertEqual(page.status_code, 200)
        self.assertIn('type="password"', page.text)
        self.assertEqual(stylesheet.status_code, 200)

    async def test_wrong_password_is_delayed_and_opens_no_session(self) -> None:
        with patch.object(self.main, "LOGIN_FAILURE_DELAY_SECONDS", 0.05):
            async with self.client() as client:
                started = time.monotonic()
                response = await client.post("/login", data={"password": "mauvais"})
                elapsed = time.monotonic() - started
                status = await client.get("/api/status")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?erreur=1")
        self.assertNotIn("set-cookie", response.headers)
        self.assertGreaterEqual(elapsed, 0.05)
        self.assertEqual(status.status_code, 401)

    async def test_correct_password_opens_a_session(self) -> None:
        async with self.client() as client:
            response = await client.post("/login", data={"password": APP_PASSWORD})
            index = await client.get("/")
            status = await client.get("/api/status")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        cookie = response.headers["set-cookie"].lower()
        for attribute in ("deezer_mix_session=", "httponly", "secure", "samesite=lax", "max-age=2592000"):
            self.assertIn(attribute, cookie)
        self.assertEqual(index.status_code, 200)
        self.assertEqual(status.status_code, 200)

    async def test_session_signed_with_another_password_is_rejected(self) -> None:
        # Couvre aussi le changement d'APP_PASSWORD, qui doit deconnecter tout le monde.
        token = self.main.make_session_token("ancien-mot-de-passe", int(time.time()) + 3600)
        async with self.client() as client:
            client.cookies.set("deezer_mix_session", token)
            response = await client.get("/api/status")

        self.assertEqual(response.status_code, 401)

    async def test_expired_session_is_rejected(self) -> None:
        token = self.main.make_session_token(APP_PASSWORD, int(time.time()) - 1)
        async with self.client() as client:
            client.cookies.set("deezer_mix_session", token)
            response = await client.get("/api/status")

        self.assertEqual(response.status_code, 401)

    async def test_non_ascii_session_is_rejected_without_crashing(self) -> None:
        # compare_digest leve TypeError sur une str non ASCII : ce serait une 500.
        self.assertFalse(self.main.is_valid_session_token("9999999999.é", APP_PASSWORD))
        # "²".isdigit() est vrai mais int("²") leve ValueError.
        self.assertFalse(self.main.is_valid_session_token("²." + "0" * 64, APP_PASSWORD))

    async def test_malformed_session_is_rejected(self) -> None:
        async with self.client() as client:
            client.cookies.set("deezer_mix_session", "n-importe-quoi")
            response = await client.get("/api/status")

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
