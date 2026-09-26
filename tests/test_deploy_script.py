"""Comportement de deploy/deploy.sh face a un client docker simule.

Le script pilote la production : on verifie la version et la compose qui
tournent reellement a l'issue de chaque scenario (succes, pull refuse,
conteneur malade, rollback), pas le texte du script. Porte depuis
garmin-parser/tests/test_deploy_script.py.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "deploy" / "deploy.sh"
IMAGE_REPO = "ghcr.io/breraud/deezer-merger"

# Faux client docker. `compose up` memorise le tag et la compose demarres dans
# $FAKE_STATE ; FAKE_MISSING_TAG fait echouer le pull de ce tag ;
# FAKE_UNHEALTHY_TAGS rend le conteneur malade quand l'un de ces tags tourne ;
# FAKE_IMAGE_TAGS liste les tags presents sur l'hote (`image ls` et
# `image inspect`) ; `image rm` note l'image supprimee ; chaque pull est note. `login` range le jeton recu sur stdin dans la config docker
# courante, comme le vrai client.
FAKE_DOCKER = r"""#!/usr/bin/env bash
set -eu
tag() { sed -n 's/^DEEZER_IMAGE_TAG=//p' "$DEPLOY_DIR/.env" | tail -n 1; }
config_dir() { printf '%s' "${DOCKER_CONFIG:-$HOME/.docker}"; }
case "$1 ${2:-}" in
  "login ghcr.io")
    mkdir -p "$(config_dir)"
    cat > "$(config_dir)/fake-auth" ;;
  "compose pull")
    [ "$(tag)" != "${FAKE_MISSING_TAG:-}" ] || exit 1
    # FAKE_REQUIRED_TOKEN : ghcr exige ce jeton dans la config docker du pull.
    if [ -n "${FAKE_REQUIRED_TOKEN:-}" ]; then
      [ "$(cat "$(config_dir)/fake-auth" 2>/dev/null)" = "$FAKE_REQUIRED_TOKEN" ] || exit 1
    fi
    config_dir > "$FAKE_STATE/pull-config"
    tag >> "$FAKE_STATE/pulls" ;;
  "compose up")
    tag > "$FAKE_STATE/running"
    cat "$DEPLOY_DIR/docker-compose.yml" > "$FAKE_STATE/running-compose" ;;
  "compose ps")
    if [ "${3:-}" = "-q" ]; then echo app-id; fi ;;
  "inspect -f")
    case " ${FAKE_UNHEALTHY_TAGS:-} " in
      *" $(cat "$FAKE_STATE/running") "*) echo unhealthy ;;
      *) echo healthy ;;
    esac ;;
  "image ls")
    for t in ${FAKE_IMAGE_TAGS:-}; do echo "$t"; done ;;
  "image rm")
    echo "$3" >> "$FAKE_STATE/removed" ;;
  "image inspect")
    case " ${FAKE_IMAGE_TAGS:-} " in
      *" ${3##*:} "*) exit 0 ;;
      *) exit 1 ;;
    esac ;;
esac
exit 0
"""


class DeployScriptTests(unittest.TestCase):
    """Production sur v1 (compose v1), prete a recevoir une nouvelle version."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)

        self.deploy_dir = tmp / "deezer-merger"
        self.deploy_dir.mkdir()
        (self.deploy_dir / "docker-compose.yml").write_text("compose v1\n")
        (self.deploy_dir / ".env").write_text("DEEZER_ARL=arl\nDEEZER_IMAGE_TAG=v1\n")
        (self.deploy_dir / "state.json").write_text("{}\n")

        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)

        self.state = tmp / "state"
        self.state.mkdir()
        (self.state / "running").write_text("v1\n")
        (self.state / "running-compose").write_text("compose v1\n")

        # Config docker partagee du VPS, que d'autres projets vident par logout.
        home = tmp / "home"
        (home / ".docker").mkdir(parents=True)
        (home / ".docker" / "config.json").write_text('{"auths": {}}')
        self.home = home

        self.env = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DEPLOY_DIR": str(self.deploy_dir),
            "FAKE_STATE": str(self.state),
            "HEALTH_TIMEOUT_SECONDS": "5",
            # En production, state.json appartient a l'uid 10001 du conteneur ;
            # ici, a l'utilisateur qui lance les tests.
            "STATE_UID": str(os.getuid()),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- aides ----------------------------------------------------------------

    def run_deploy(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), *args],
            env=self.env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def running_tag(self) -> str:
        return (self.state / "running").read_text().strip()

    def running_compose(self) -> str:
        return (self.state / "running-compose").read_text()

    def env_value(self, key: str) -> str | None:
        lines = (self.deploy_dir / ".env").read_text().splitlines()
        values = [line.split("=", 1)[1] for line in lines if line.startswith(f"{key}=")]
        return values[-1] if values else None

    def ship_compose(self, content: str) -> None:
        """Ce que la CI depose avant de lancer le script."""
        (self.deploy_dir / "docker-compose.next.yml").write_text(content)

    def removed_images(self) -> list[str]:
        removed = self.state / "removed"
        return removed.read_text().split() if removed.exists() else []

    # --- version et tags --------------------------------------------------------

    def test_successful_deploy_runs_target_and_remembers_previous(self) -> None:
        result = self.run_deploy("v2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.running_tag(), "v2")
        self.assertEqual(self.env_value("DEEZER_IMAGE_TAG"), "v2")
        self.assertEqual(self.env_value("DEEZER_PREVIOUS_IMAGE_TAG"), "v1")

    def test_rejected_pull_leaves_running_version_untouched(self) -> None:
        self.env["FAKE_MISSING_TAG"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.running_tag(), "v1")
        self.assertEqual(self.env_value("DEEZER_IMAGE_TAG"), "v1")

    def test_unhealthy_container_puts_previous_version_back_in_service(self) -> None:
        """Restaurer .env ne suffit pas : le conteneur doit revenir sur v1."""
        self.env["FAKE_UNHEALTHY_TAGS"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.running_tag(), "v1")
        self.assertEqual(self.env_value("DEEZER_IMAGE_TAG"), "v1")
        self.assertIn("v1 remis en service", result.stderr)

    def test_failed_deploy_does_not_point_to_an_older_version(self) -> None:
        """--rollback vise la version d'avant v1 : le conseiller apres un echec
        de v2 ferait reculer la production de deux versions."""
        (self.deploy_dir / ".env").write_text("DEEZER_IMAGE_TAG=v1\nDEEZER_PREVIOUS_IMAGE_TAG=v0\n")
        self.env["FAKE_UNHEALTHY_TAGS"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("--rollback", result.stderr)
        self.assertEqual(self.env_value("DEEZER_PREVIOUS_IMAGE_TAG"), "v0")

    def test_restore_that_stays_unhealthy_is_not_reported_as_restored(self) -> None:
        """Un message « remis en service » sur un conteneur malade egare la
        personne qui intervient pendant l'incident."""
        self.env["FAKE_UNHEALTHY_TAGS"] = "v1 v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.running_tag(), "v1")
        self.assertNotIn("v1 remis en service", result.stderr)
        self.assertIn("non sain", result.stderr)

    def test_failed_first_deploy_leaves_no_tag_behind(self) -> None:
        """Sans version precedente, rien a restaurer : le tag de la version
        ratee ne doit pas rester, sinon le deploiement suivant la retiendrait
        comme version de rollback."""
        (self.deploy_dir / ".env").write_text("DEEZER_ARL=arl\n")
        self.env["FAKE_UNHEALTHY_TAGS"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(self.env_value("DEEZER_IMAGE_TAG"))
        self.assertEqual(self.env_value("DEEZER_ARL"), "arl")

    def test_second_rollback_is_refused_instead_of_returning_to_the_left_version(self) -> None:
        """Un rollback quitte une version jugee mauvaise : un second --rollback
        ne doit pas y revenir sans qu'on le demande explicitement."""
        (self.deploy_dir / ".env").write_text("DEEZER_IMAGE_TAG=v2\nDEEZER_PREVIOUS_IMAGE_TAG=v1\n")
        (self.deploy_dir / "docker-compose.yml").write_text("compose v2\n")
        (self.deploy_dir / "docker-compose.previous.yml").write_text("compose v1\n")
        (self.state / "running").write_text("v2\n")

        first = self.run_deploy("--rollback")
        second = self.run_deploy("--rollback")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(self.running_tag(), "v1")
        self.assertIsNone(self.env_value("DEEZER_PREVIOUS_IMAGE_TAG"))
        self.assertFalse((self.deploy_dir / "docker-compose.previous.yml").exists())
        self.assertIn("./deploy.sh <tag>", second.stderr)

    def test_invalid_tag_is_refused_before_anything_changes(self) -> None:
        """Le tag vient d'une saisie (workflow_dispatch) et finit dans .env :
        une quote ou un saut de ligne casserait la commande ou le fichier."""
        for tag in ("v2'; touch pwned; '", "v2\nDEEZER_ARL=vole", "", "-v2"):
            with self.subTest(tag=tag):
                result = self.run_deploy(tag) if tag else self.run_deploy("--ghcr-token-stdin", "")

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.running_tag(), "v1")
                self.assertEqual(
                    (self.deploy_dir / ".env").read_text(), "DEEZER_ARL=arl\nDEEZER_IMAGE_TAG=v1\n"
                )

    # --- compose ------------------------------------------------------------------

    def test_new_compose_goes_live_with_the_new_version(self) -> None:
        self.ship_compose("compose v2\n")

        result = self.run_deploy("v2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.running_compose(), "compose v2\n")
        self.assertEqual((self.deploy_dir / "docker-compose.yml").read_text(), "compose v2\n")
        self.assertEqual(
            (self.deploy_dir / "docker-compose.previous.yml").read_text(), "compose v1\n"
        )
        self.assertFalse((self.deploy_dir / "docker-compose.next.yml").exists())

    def test_unhealthy_deploy_restores_previous_compose_with_previous_image(self) -> None:
        """La CI a deja depose la compose de v2 : l'ancienne image doit repartir
        avec l'ancienne compose, sinon la « restauration » tourne avec la
        configuration qui vient d'echouer."""
        self.ship_compose("compose v2\n")
        self.env["FAKE_UNHEALTHY_TAGS"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.running_tag(), "v1")
        self.assertEqual(self.running_compose(), "compose v1\n")
        self.assertEqual((self.deploy_dir / "docker-compose.yml").read_text(), "compose v1\n")
        self.assertFalse((self.deploy_dir / "docker-compose.next.yml").exists())

    def test_rejected_pull_keeps_running_compose(self) -> None:
        self.ship_compose("compose v2\n")
        self.env["FAKE_MISSING_TAG"] = "v2"

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.deploy_dir / "docker-compose.yml").read_text(), "compose v1\n")

    def test_rollback_restores_previous_compose(self) -> None:
        (self.deploy_dir / ".env").write_text("DEEZER_IMAGE_TAG=v2\nDEEZER_PREVIOUS_IMAGE_TAG=v1\n")
        (self.deploy_dir / "docker-compose.yml").write_text("compose v2\n")
        (self.deploy_dir / "docker-compose.previous.yml").write_text("compose v1\n")
        (self.state / "running").write_text("v2\n")

        result = self.run_deploy("--rollback")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.running_tag(), "v1")
        self.assertEqual(self.running_compose(), "compose v1\n")

    # --- etat applicatif ------------------------------------------------------------

    def test_missing_state_file_is_refused_before_touching_docker(self) -> None:
        """Monte en bind, un state.json absent deviendrait un repertoire."""
        (self.deploy_dir / "state.json").unlink()

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("state.json absent", result.stderr)
        self.assertEqual(self.running_tag(), "v1")
        self.assertFalse((self.deploy_dir / "state.json").exists())

    def test_state_file_not_owned_by_container_user_is_refused(self) -> None:
        """Lisible mais pas inscriptible : le conteneur resterait sain, puis
        « Generer » publierait la playlist sans pouvoir enregistrer l'etat."""
        self.env["STATE_UID"] = str(os.getuid() + 1)

        result = self.run_deploy("v2")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"uid {os.getuid() + 1}", result.stderr)
        self.assertEqual(self.running_tag(), "v1")
        self.assertEqual(self.env_value("DEEZER_IMAGE_TAG"), "v1")

    # --- images ------------------------------------------------------------------

    def test_success_keeps_only_running_and_previous_images(self) -> None:
        """Le disque du VPS est partage : sans menage, chaque deploiement y
        laisse une image."""
        self.env["FAKE_IMAGE_TAGS"] = "v0 v1 v2 ancien"

        result = self.run_deploy("v2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            sorted(self.removed_images()), [f"{IMAGE_REPO}:ancien", f"{IMAGE_REPO}:v0"]
        )

    def test_failed_deploy_removes_no_image(self) -> None:
        self.env["FAKE_IMAGE_TAGS"] = "v0 v1 v2"
        self.env["FAKE_UNHEALTHY_TAGS"] = "v2"

        self.run_deploy("v2")

        self.assertEqual(self.removed_images(), [])

    def test_rollback_needs_no_registry_when_the_image_is_on_the_host(self) -> None:
        """Pendant un incident, le rollback ne doit dependre ni d'un jeton ghcr
        (images privees) ni de la disponibilite du registre."""
        (self.deploy_dir / ".env").write_text("DEEZER_IMAGE_TAG=v2\nDEEZER_PREVIOUS_IMAGE_TAG=v1\n")
        (self.state / "running").write_text("v2\n")
        self.env["FAKE_IMAGE_TAGS"] = "v1 v2"
        self.env["FAKE_REQUIRED_TOKEN"] = "jeton-que-le-vps-n-a-pas"

        result = self.run_deploy("--rollback")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.running_tag(), "v1")
        self.assertFalse((self.state / "pulls").exists())

    def test_latest_is_pulled_even_when_present(self) -> None:
        """`latest` bouge : l'avoir sur l'hote ne dit pas qu'il est a jour."""
        self.env["FAKE_IMAGE_TAGS"] = "latest"

        result = self.run_deploy("latest")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "pulls").read_text().split(), ["latest"])

    # --- jeton ghcr -----------------------------------------------------------------

    def test_ci_token_on_stdin_authenticates_the_pull(self) -> None:
        """La CI transmet son GITHUB_TOKEN ephemere : aucun jeton permanent sur le VPS."""
        self.env["FAKE_REQUIRED_TOKEN"] = "jeton-ci"
        self.env["GHCR_USER"] = "ci-bot"

        result = self.run_deploy("--ghcr-token-stdin", "v2", stdin="jeton-ci")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.running_tag(), "v2")
        self.assertNotIn("jeton-ci", result.stdout + result.stderr)

    def test_pull_credentials_never_touch_the_shared_docker_config(self) -> None:
        """~/.docker/config.json est partage : le runner d'insastronaute y fait
        `docker logout ghcr.io` et effacait les identifiants de Garmin."""
        shared = self.home / ".docker"
        self.env["FAKE_REQUIRED_TOKEN"] = "jeton-ci"
        self.env["GHCR_USER"] = "ci-bot"

        self.run_deploy("--ghcr-token-stdin", "v2", stdin="jeton-ci")

        pull_config = Path((self.state / "pull-config").read_text())
        self.assertNotEqual(pull_config, shared)
        self.assertFalse(pull_config.exists(), "la config temporaire doit etre supprimee")
        self.assertEqual((shared / "config.json").read_text(), '{"auths": {}}')


if __name__ == "__main__":
    unittest.main()
