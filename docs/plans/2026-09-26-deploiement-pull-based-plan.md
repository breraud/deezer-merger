# Déploiement pull-based de Deezer Mix : plan d'exécution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Déployer Deezer Mix comme Garmin (CI → image ghcr → `deploy.sh` sur le VPS), et mettre les workflows des deux projets sur des actions Node 24 et un runner épinglé.

**Architecture:** Chaque dépôt garde sa propre chaîne. La CI teste, construit l'image, la publie sur ghcr.io, puis envoie `docker-compose.yml` et `deploy/deploy.sh` au VPS et lance le script avec un jeton ghcr éphémère. Le script tire l'image, attend le healthcheck et remet la version précédente en service en cas d'échec.

**Tech Stack:** GitHub Actions, Docker/Compose, ghcr.io, Traefik v3, uv 0.12, Python 3.12, FastAPI/uvicorn, Bash.

**Spec:** `docs/plans/2026-09-26-deploiement-pull-based-design.md`

## Global Constraints

- Dépôt Deezer : `/home/brehan/Documents/Projet_Perso/deezer_sync` (GitHub `breraud/deezer-merger`). Dépôt Garmin : `/home/brehan/Documents/Projet_Perso/garmin_scrapper` (GitHub `breraud/garmin-parser`).
- Branche de déploiement Deezer : `main`. Un push sur `main` déploie la production, dans les deux dépôts.
- Python 3.12 ; uv `0.12.17` en CI ; images de base `ghcr.io/astral-sh/uv:0.12-python3.12-trixie-slim` et `python:3.12-slim-trixie`.
- Image : `ghcr.io/breraud/deezer-merger`, tags `<sha>` et `latest`.
- VPS : `debian@beraud.dev`, dossier `/opt/deezer-merger`, projet compose `deezer-merger`, service `deezer-app`, port 3457, domaine `deezer.beraud.dev`, réseau docker externe `proxy`.
- Conteneur non-root : uid 10001 (`appuser`).
- Healthcheck et vérifications : `GET /` uniquement. Ne jamais appeler `/api/status`, `/api/generate`, `/api/refresh/*` ni `/api/reset` : ils peuvent republier la playlist Deezer.
- Actions : `actions/checkout@v7`, `actions/setup-node@v7`, `astral-sh/setup-uv@v10.2.0`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/build-push-action@v7`. Runner : `ubuntu-26.04`.
- Secrets de l'environnement `production` de `deezer-merger` : `DEEZER_SSH_KEY`, `DEEZER_HOST`, `DEEZER_USER`, `DEEZER_SSH_PORT` (facultatif).
- Commentaires des fichiers d'infra : français sans accents, comme ceux de Garmin. Messages de commit : anglais dans deezer-merger (convention du dépôt), français dans garmin-parser.
- Chaque commit se termine par `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Les étapes marquées **⚠ Accord** écrivent sur le VPS partagé ou sur GitHub : les exécuter seulement après un accord explicite donné pour cette étape.
- Docker local sans DNS (VPN) : tout `docker build` qui télécharge des paquets passe `--add-host` pour `pypi.org` et `files.pythonhosted.org` (vérifié le 2026-09-26).

## Review Focus

1. `state.json` absent sur le VPS : docker créerait un **répertoire** à sa place et l'application repartirait d'un état vide. `deploy.sh` doit refuser avant tout `docker compose` (test : Task 5, étape 1).
2. `state.json` non inscriptible par l'uid 10001 : l'application lit l'état, mais toute écriture échoue. Test d'écriture en uid 10001 dans l'image (Task 3), propriétaire vérifié sur le VPS (Task 8).
3. Pools vides au démarrage : le lifespan appelle `reload_all_data()`, donc Deezer, et réécrit `state.json`. Le test local utilise un état non vide ; en prod, les logs ne doivent contenir ni `Falling back to default state` ni `Traceback` (Task 9).
4. Échec du premier déploiement : aucun tag précédent, donc pas de restauration automatique. L'ancienne image locale doit exister avant la bascule (Task 8) et le retour manuel est écrit (Task 9).
5. `.env` passé en 600 au nom de `debian` : compose (lancé par `debian`) doit toujours le lire (Task 8).

## Écart assumé par rapport à la spec

La spec (bascule, étape 3) prévoit d'ajouter `DEEZER_IMAGE_TAG` au `.env` avant le premier déploiement. Le plan ne le fait pas : avec `DEEZER_IMAGE_TAG=latest` préenregistré, un échec du premier déploiement « restaurerait » `latest`, qui est la nouvelle image elle-même. Sans tag préalable, `deploy.sh` n'essaie aucune restauration trompeuse, écrit le tag lui-même au premier succès, et le retour manuel de la Task 9 s'applique.

---

### Task 1: Garmin, actions Node 24 et runner épinglé

Fait en premier : il valide les nouvelles versions et `ubuntu-26.04` sur une chaîne qui fonctionne déjà.

**Files:**
- Modify: `garmin_scrapper/.github/workflows/deploy.yml` (lignes `runs-on:` et `uses:`)

**Interfaces:**
- Consumes: rien.
- Produces: la preuve que les versions et le runner des Global Constraints fonctionnent ; Task 6 les reprend.

- [ ] **Step 1: Écrire la vérification**

```bash
cd /home/brehan/Documents/Projet_Perso/garmin_scrapper
check_workflow() {
  ! grep -nE 'runs-on: ubuntu-latest|actions/checkout@v4|astral-sh/setup-uv@v5|actions/setup-node@v4|docker/setup-buildx-action@v3|docker/login-action@v3|docker/build-push-action@v6' .github/workflows/deploy.yml
}
```

- [ ] **Step 2: Vérifier qu'elle échoue**

Run: `check_workflow; echo "exit=$?"`
Expected: les lignes obsolètes s'affichent, `exit=1`.

- [ ] **Step 3: Mettre à jour le workflow**

```bash
sed -i \
  -e 's/runs-on: ubuntu-latest/runs-on: ubuntu-26.04/' \
  -e 's#actions/checkout@v4#actions/checkout@v7#' \
  -e 's#astral-sh/setup-uv@v5#astral-sh/setup-uv@v10.2.0#' \
  -e 's#actions/setup-node@v4#actions/setup-node@v7#' \
  -e 's#docker/setup-buildx-action@v3#docker/setup-buildx-action@v4#' \
  -e 's#docker/login-action@v3#docker/login-action@v4#' \
  -e 's#docker/build-push-action@v6#docker/build-push-action@v7#' \
  .github/workflows/deploy.yml
```

- [ ] **Step 4: Vérifier**

Run: `check_workflow; echo "exit=$?"; uvx --from actionlint-py actionlint .github/workflows/deploy.yml && echo lint-ok`
Expected: aucune ligne, `exit=0`, `lint-ok`. `git diff --stat` : 1 fichier, uniquement des lignes `runs-on` et `uses`.

- [ ] **Step 5: Commit et push (déploie Garmin)**

```bash
git add .github/workflows/deploy.yml
git commit -q -F - <<'EOF'
ci: actions en Node 24 et runner ubuntu-26.04

Supprime les avertissements de depreciation de Node 20 et l'avis de
migration d'ubuntu-latest vers Ubuntu 26.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
git push origin main
```

- [ ] **Step 6: Suivre le run et vérifier l'absence d'avertissements**

```bash
sleep 5
RUN=$(gh run list -R breraud/garmin-parser --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN" -R breraud/garmin-parser --exit-status --interval 20 >/dev/null; echo "run exit=$?"
for u in $(gh api "repos/breraud/garmin-parser/actions/runs/$RUN/jobs" --jq '.jobs[].check_run_url'); do
  gh api "$u/annotations" --jq '.[] | "\(.annotation_level): \(.message)"'
done
ssh debian@beraud.dev 'docker ps --format "{{.Names}} {{.Image}} {{.Status}}" | grep garmin'
curl -sS -o /dev/null -w '%{http_code}\n' https://garmin.beraud.dev/
```

Expected: `run exit=0`, **aucune** annotation, deux conteneurs `healthy` sur le nouveau SHA, `200`. Si un job échoue à cause d'`ubuntu-26.04`, repasser les trois `runs-on` en `ubuntu-24.04`, le signaler, et reporter le même choix en Task 6.

---

### Task 2: Deezer, branche `main` et migration uv

**Files:**
- Create: `pyproject.toml`, `.python-version`, `uv.lock`
- Delete: `requirements.txt`

**Interfaces:**
- Consumes: rien.
- Produces: `uv sync --locked` fonctionnel ; `uv.lock` et `.python-version` copiés par le Dockerfile (Task 3) ; commande de test `uv run python -m unittest discover -s tests -t .` (Task 6).

- [ ] **Step 1: Placer `main` sur le travail en cours**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
git checkout main
git merge --ff-only deploy/docker-prod
git log --oneline -1   # le commit de la spec, puis ce plan une fois commité
```

- [ ] **Step 2: Vérifier que la synchronisation uv échoue**

Run: `uv sync --locked; echo "exit=$?"`
Expected: erreur (aucun `pyproject.toml`), `exit=2`.

- [ ] **Step 3: Déclarer le projet**

`pyproject.toml` :

```toml
[project]
name = "deezer-merger"
version = "0.1.0"
description = "Fusionne trois playlists Deezer dans une playlist cible."
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.136.0",
  "uvicorn>=0.46.0",
  "deezer-python-gql>=0.9.0",
  "python-dotenv>=1.2.2",
]

[tool.uv]
# Deux modules a la racine (main.py, deezer_client.py) : rien a empaqueter.
package = false
```

`.python-version` :

```
3.12
```

```bash
git rm -q requirements.txt
uv lock
```

Si `uv lock` signale une dépendance incompatible avec Python 3.12, s'arrêter et le signaler : ne pas changer la version de Python sans accord.

- [ ] **Step 4: Vérifier**

Run:

```bash
uv sync --locked && uv run python --version
uv run python -m unittest discover -s tests -t . 2>&1 | tail -3
uv export --no-hashes --no-dev | grep -cE '^(fastapi|uvicorn|deezer-python-gql|python-dotenv)=='
uv export --no-hashes --no-dev > /tmp/deezer-requirements.txt && uvx pip-audit -r /tmp/deezer-requirements.txt
```

Expected: `Python 3.12.x` (uv recrée `.venv` en 3.12), `Ran 21 tests` puis `OK`, `4`, `No known vulnerabilities found`. Une vulnérabilité connue : relever la borne concernée dans `pyproject.toml`, relancer `uv lock`, revérifier.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version uv.lock
git commit -q -F - <<'EOF'
build: manage dependencies with uv and a lockfile

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: Deezer, image de production

**Files:**
- Modify: `Dockerfile` (réécrit)
- Modify: `.dockerignore`

**Interfaces:**
- Consumes: `pyproject.toml`, `uv.lock`, `.python-version` (Task 2).
- Produces: une image qui écoute sur 3457 en uid 10001, sert `/` et lit `STATE_FILE_PATH`. Tag local `ghcr.io/breraud/deezer-merger:local`, réutilisé par la Task 4.

- [ ] **Step 1: Écrire le test de l'image**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
SMOKE=$(mktemp -d)
cat > "$SMOKE/state.json" <<'EOF'
{"source_pools": {"player1": [{"id": "1", "title": "Titre test", "artist": "Artiste test"}], "player2": [], "player3": []}, "players": {}, "mix": [{"id": "1", "title": "Titre test", "artist": "Artiste test"}]}
EOF
# 666 : le test local n'a pas sudo pour donner le fichier a l'uid 10001.
chmod 666 "$SMOKE/state.json"

smoke_image() {
  docker rm -f deezer-smoke >/dev/null 2>&1
  docker run -d --name deezer-smoke -p 127.0.0.1:3457:3457 \
    -e DEEZER_ARL=arl-test -e PLAYLIST_SOURCE_1=1 -e PLAYLIST_SOURCE_2=2 \
    -e PLAYLIST_SOURCE_3=3 -e PLAYLIST_CIBLE=9 -e STATE_FILE_PATH=/app/state.json \
    -v "$SMOKE/state.json:/app/state.json" "$1" >/dev/null || return 1
  curl -fsS -o /dev/null -w 'GET / -> %{http_code}\n' --retry 15 --retry-connrefused --retry-delay 1 http://127.0.0.1:3457/ || return 1
  [ "$(docker exec deezer-smoke id -u)" = 10001 ] || { echo "uid != 10001"; return 1; }
  docker exec deezer-smoke python -c "from main import load_state, save_state; save_state(load_state())" || return 1
  ! docker logs deezer-smoke 2>&1 | grep -E 'Falling back to default state|Traceback'
}
```

- [ ] **Step 2: Vérifier qu'il échoue sur l'image actuelle**

```bash
PYPI_IP=$(getent ahostsv4 pypi.org | awk '{print $1; exit}')
FILES_IP=$(getent ahostsv4 files.pythonhosted.org | awk '{print $1; exit}')
docker build --add-host "pypi.org:$PYPI_IP" --add-host "files.pythonhosted.org:$FILES_IP" -t deezer-merger:old .
smoke_image deezer-merger:old; echo "exit=$?"
```

Expected: `exit=1`. L'ancien Dockerfile installe `requirements.txt`, supprimé en Task 2 : le build échoue, ou l'image tourne en root (`uid != 10001`).

- [ ] **Step 3: Réécrire le Dockerfile**

`Dockerfile` :

```dockerfile
# Image construite par la CI et poussee sur ghcr.io : le VPS ne build rien.
# uv 0.12 n'est publie qu'en trixie. Les deux etapes doivent nommer la meme
# version de Debian : le venv construit ici est copie tel quel plus bas.
FROM ghcr.io/astral-sh/uv:0.12-python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev


FROM python:3.12-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser main.py deezer_client.py ./
COPY --chown=appuser:appuser static ./static

USER appuser

EXPOSE 3457

# 0.0.0.0 est obligatoire : le conteneur est joint par Traefik via le reseau
# docker, pas par la loopback. L'exposition publique est controlee par Traefik.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3457"]
```

`.dockerignore` : garder le contenu actuel et ajouter à la fin :

```
.codex
tests
docs
deploy
.github
```

- [ ] **Step 4: Vérifier**

```bash
docker build --add-host "pypi.org:$PYPI_IP" --add-host "files.pythonhosted.org:$FILES_IP" -t ghcr.io/breraud/deezer-merger:local .
smoke_image ghcr.io/breraud/deezer-merger:local; echo "exit=$?"
docker rm -f deezer-smoke >/dev/null; docker rmi deezer-merger:old >/dev/null 2>&1 || true
```

Expected: `GET / -> 200`, aucune ligne de log suspecte, `exit=0`. Garder l'image `:local` et `$SMOKE` pour la Task 4. Un échec « dns error » ou `EAI_AGAIN` vient de la machine, pas du Dockerfile : revérifier les `--add-host`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -q -F - <<'EOF'
build: two-stage uv image running as a non-root user

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Deezer, compose de production

**Files:**
- Modify: `docker-compose.yml` (réécrit)
- Modify: `.env.example` (réécrit)

**Interfaces:**
- Consumes: image `ghcr.io/breraud/deezer-merger:local` et `$SMOKE/state.json` (Task 3).
- Produces: service `deezer-app` avec healthcheck, lu par `deploy.sh` (Task 5) ; variable `DEEZER_IMAGE_TAG`.

- [ ] **Step 1: Écrire la vérification**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
check_compose() {
  local dir; dir=$(mktemp -d)
  cp docker-compose.yml "$dir/"
  cp .env.example "$dir/.env"   # jamais le vrai .env local, qui contient l'ARL
  (cd "$dir" && docker compose config --format json) > "$dir/config.json" || return 1
  python3 - "$dir/config.json" <<'EOF'
import json, sys
svc = json.load(open(sys.argv[1]))["services"]["deezer-app"]
assert svc["image"] == "ghcr.io/breraud/deezer-merger:latest", svc.get("image")
assert "build" not in svc and not svc.get("ports"), "build ou ports presents"
assert "http://127.0.0.1:3457/" in " ".join(svc["healthcheck"]["test"]), "sonde != /"
assert svc["labels"]["traefik.http.services.deezer.loadbalancer.server.port"] == "3457"
assert list(svc["networks"]) == ["proxy"], svc["networks"]
print("compose ok")
EOF
}
```

- [ ] **Step 2: Vérifier qu'elle échoue**

Run: `check_compose; echo "exit=$?"`
Expected: `AssertionError` (l'actuelle n'a pas d'`image`), `exit=1`.

- [ ] **Step 3: Écrire la compose et l'exemple d'environnement**

`docker-compose.yml` :

```yaml
# Stack de production (VPS /opt/deezer-merger).
#
# L'image est CONSTRUITE PAR LA CI et poussee sur ghcr.io : le VPS ne build
# rien et ne contient aucune source. Le deploiement se resume a
# `deploy.sh <tag>` qui tire le tag demande et recree le conteneur.
#
# DEEZER_IMAGE_TAG selectionne la version deployee (SHA de commit, ou
# `latest`). Un rollback = `./deploy.sh --rollback`.
#
# Aucun port publie sur l'hote : Traefik joint le conteneur par le reseau
# docker externe `proxy` et termine TLS.
#
# Developpement local : `uv run uvicorn main:app --reload --port 3457`, pas
# ce fichier.
services:
  deezer-app:
    image: ghcr.io/breraud/deezer-merger:${DEEZER_IMAGE_TAG:-latest}
    restart: unless-stopped
    env_file:
      - ./.env
    environment:
      STATE_FILE_PATH: /app/state.json
    volumes:
      # Un fichier : deploy.sh verifie qu'il existe, sinon docker creerait un
      # repertoire a sa place.
      - ./state.json:/app/state.json
    networks:
      - proxy
    healthcheck:
      # Sonde sur / : /api/status peut regenerer le mix et republier la
      # playlist Deezer. L'image n'a ni curl ni wget : on passe par Python.
      test:
        - CMD
        - python
        - -c
        - import urllib.request; urllib.request.urlopen("http://127.0.0.1:3457/")
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.deezer.rule=Host(`deezer.beraud.dev`)"
      - "traefik.http.services.deezer.loadbalancer.server.port=3457"
      - "traefik.docker.network=proxy"

networks:
  proxy:
    external: true
```

`.env.example` :

```
# Copier vers .env A LA RACINE DU DEPLOIEMENT (/opt/deezer-merger/.env sur le
# VPS, en chmod 600). Sert a la substitution de variables de
# docker-compose.yml et d'env_file au conteneur. En local, uvicorn lit aussi
# ce fichier via python-dotenv.
DEEZER_ARL=
PLAYLIST_SOURCE_1=
PLAYLIST_SOURCE_2=
PLAYLIST_SOURCE_3=
PLAYLIST_CIBLE=

# Tag d'image deploye. Ecrit par deploy/deploy.sh ; ne pas editer a la main.
DEEZER_IMAGE_TAG=latest
```

- [ ] **Step 4: Vérifier la configuration, puis le healthcheck en conditions réelles**

```bash
check_compose; echo "exit=$?"

RUNDIR=$(mktemp -d)
cp docker-compose.yml "$RUNDIR/"
cp "$SMOKE/state.json" "$RUNDIR/state.json" && chmod 666 "$RUNDIR/state.json"
printf 'DEEZER_ARL=arl-test\nPLAYLIST_SOURCE_1=1\nPLAYLIST_SOURCE_2=2\nPLAYLIST_SOURCE_3=3\nPLAYLIST_CIBLE=9\nDEEZER_IMAGE_TAG=local\n' > "$RUNDIR/.env"
created_proxy=0
docker network inspect proxy >/dev/null 2>&1 || { docker network create proxy >/dev/null && created_proxy=1; }
(cd "$RUNDIR" && docker compose -p deezer-smoke up -d)
for i in $(seq 1 30); do
  s=$(docker inspect -f '{{.State.Health.Status}}' "$(cd "$RUNDIR" && docker compose -p deezer-smoke ps -q deezer-app)")
  [ "$s" = healthy ] && break; sleep 2
done; echo "health=$s"
(cd "$RUNDIR" && docker compose -p deezer-smoke down)
[ "$created_proxy" = 1 ] && docker network rm proxy >/dev/null
```

Expected: `compose ok`, `exit=0`, puis `health=healthy`.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -q -F - <<'EOF'
deploy: production compose pulling the ghcr image behind Traefik

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Deezer, script de déploiement

**Files:**
- Create: `deploy/deploy.sh` (exécutable)

**Interfaces:**
- Consumes: `docker-compose.yml` (service `deezer-app`, variable `DEEZER_IMAGE_TAG`) de la Task 4.
- Produces: `deploy.sh [--ghcr-token-stdin] [<tag>|--rollback]`, avec `DEPLOY_DIR` (défaut `/opt/deezer-merger`), `GHCR_USER` dans l'environnement et le jeton sur stdin. Clés écrites dans `.env` : `DEEZER_IMAGE_TAG`, `DEEZER_PREVIOUS_IMAGE_TAG`. Appelé par la Task 6.

- [ ] **Step 1: Écrire les tests des chemins d'échec**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
make_deploy_dir() {
  local dir; dir=$(mktemp -d)
  cp docker-compose.yml "$dir/"
  cp deploy/deploy.sh "$dir/" 2>/dev/null
  printf 'DEEZER_ARL=arl-test\nPLAYLIST_SOURCE_1=1\nPLAYLIST_SOURCE_2=2\nPLAYLIST_SOURCE_3=3\nPLAYLIST_CIBLE=9\nDEEZER_IMAGE_TAG=tag-precedent\n' > "$dir/.env"
  echo "$dir"
}

# 1. state.json absent : refus avant tout appel a docker.
D1=$(make_deploy_dir)
DEPLOY_DIR=$D1 bash "$D1/deploy.sh" tag-quelconque 2>&1 | tail -1
echo "exit=${PIPESTATUS[0]}"; [ ! -e "$D1/state.json" ] && echo "pas de state.json cree"

# 2. tag introuvable sur ghcr : echec du pull et tag precedent restaure.
D2=$(make_deploy_dir); echo '{}' > "$D2/state.json"
DEPLOY_DIR=$D2 bash "$D2/deploy.sh" tag-inexistant-sur-ghcr 2>&1 | tail -1
echo "exit=${PIPESTATUS[0]}"; grep '^DEEZER_IMAGE_TAG=' "$D2/.env"
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: les deux blocs ci-dessus.
Expected : `bash: .../deploy.sh: No such file or directory`, `exit=127` pour les deux cas : le script n'existe pas encore.

- [ ] **Step 3: Écrire le script**

`deploy/deploy.sh` :

```bash
#!/usr/bin/env bash
#
# Deploiement pull-based de Deezer Mix sur le VPS.
#
#   ./deploy.sh <tag>       deploie le tag demande (SHA de commit, ou `latest`)
#   ./deploy.sh             redeploie le tag actuellement enregistre
#   ./deploy.sh --rollback  revient au tag deploye precedemment
#
#   --ghcr-token-stdin, en premier argument : lit sur stdin le jeton ghcr que
#   la CI transmet (son GITHUB_TOKEN ephemere, avec GHCR_USER dans l'env).
#
# Le VPS ne construit aucune image : elle est produite par la CI et tiree
# depuis ghcr.io. Ce script est remplace a chaque deploiement par la CI, donc
# toute modification doit se faire dans le depot (deploy/deploy.sh).
#
# Pre-requis, une seule fois sur le VPS (voir deploy/SETUP.md) :
#   - /opt/deezer-merger/.env        variables Deezer (chmod 600)
#   - /opt/deezer-merger/state.json  etat applicatif, proprietaire uid 10001
#   - /opt/deezer-merger/.ghcr.env   GHCR_USER=... / GHCR_TOKEN=... (chmod 600)
#     seulement pour tirer une nouvelle image a la main : la CI fournit son
#     propre jeton, et --rollback reutilise une image deja presente.

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/deezer-merger}"
ENV_FILE="$DEPLOY_DIR/.env"
STATE_FILE="$DEPLOY_DIR/state.json"
GHCR_ENV_FILE="$DEPLOY_DIR/.ghcr.env"
SERVICE="deezer-app"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-120}"

log() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERREUR: %s\n' "$*" >&2; exit 1; }

cd "$DEPLOY_DIR" || fail "repertoire de deploiement introuvable: $DEPLOY_DIR"
[ -f docker-compose.yml ] || fail "docker-compose.yml absent de $DEPLOY_DIR"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE absent (requis par compose et par l'application)"
# Monte en bind : absent, docker creerait un repertoire a sa place et
# l'application repartirait d'un etat vide, rechargee depuis Deezer.
[ -f "$STATE_FILE" ] || fail "$STATE_FILE absent : restaurer l'etat, ou creer un fichier vide appartenant a l'uid 10001"

# --- lecture d'une cle dans le .env ------------------------------------------
read_env_key() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

# --- ecriture idempotente d'une cle dans le .env ------------------------------
write_env_key() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  # On preserve les permissions et toutes les autres lignes du fichier.
  grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  chmod --reference="$ENV_FILE" "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# --- resolution du tag a deployer ---------------------------------------------
ghcr_token_from_stdin=0
if [ "${1:-}" = "--ghcr-token-stdin" ]; then
  ghcr_token_from_stdin=1
  shift
fi

current_tag="$(read_env_key DEEZER_IMAGE_TAG)"
previous_tag="$(read_env_key DEEZER_PREVIOUS_IMAGE_TAG)"

case "${1:-}" in
  --rollback)
    [ -n "$previous_tag" ] || fail "aucun tag precedent enregistre, rollback impossible"
    target_tag="$previous_tag"
    log "rollback demande vers $target_tag"
    ;;
  "")
    [ -n "$current_tag" ] || fail "aucun tag enregistre et aucun tag fourni en argument"
    target_tag="$current_tag"
    ;;
  *)
    target_tag="$1"
    ;;
esac

log "tag cible      : $target_tag"
log "tag courant    : ${current_tag:-<aucun>}"

# --- authentification ghcr ----------------------------------------------------
# Les identifiants vivent dans un DOCKER_CONFIG propre a ce deploiement, detruit
# en sortie. ~/.docker/config.json est partage avec les autres projets du VPS :
# le runner d'insastronaute y fait `docker logout ghcr.io` en fin de job.
DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG
trap 'rm -rf "$DOCKER_CONFIG"' EXIT

ghcr_token=""
if [ "$ghcr_token_from_stdin" = 1 ]; then
  # Sans saut de ligne final, read echoue tout en remplissant la variable.
  IFS= read -r ghcr_token || true
elif [ -f "$GHCR_ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$GHCR_ENV_FILE"
  ghcr_token="${GHCR_TOKEN:-}"
fi

if [ -n "$ghcr_token" ] && [ -n "${GHCR_USER:-}" ]; then
  log "authentification ghcr.io en tant que $GHCR_USER"
  printf '%s' "$ghcr_token" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null
fi

# --- pull avant bascule -------------------------------------------------------
# On ecrit le tag AVANT le pull pour que compose resolve la bonne image, mais
# on conserve l'ancien pour pouvoir revenir en arriere si le pull ou la sante
# echouent.
write_env_key DEEZER_IMAGE_TAG "$target_tag"

restore_previous_tag() {
  if [ -n "$current_tag" ]; then
    log "restauration du tag $current_tag dans $ENV_FILE"
    write_env_key DEEZER_IMAGE_TAG "$current_tag"
  fi
}

# Une fois le conteneur recree, restaurer le .env ne suffit plus : il faut
# remettre en service la version qui tournait. --rollback n'est pas une issue,
# il vise le tag d'AVANT celui-ci.
restore_previous_version() {
  restore_previous_tag
  [ -n "$current_tag" ] || return 0
  log "remise en service de $current_tag..."
  docker compose up -d --remove-orphans \
    || fail "remise en service de $current_tag echouee — relance './deploy.sh $current_tag'"
}

log "pull de l'image..."
if ! docker compose pull; then
  restore_previous_tag
  fail "pull de l'image echoue pour le tag $target_tag (tag inexistant ou acces ghcr refuse)"
fi

log "recreation du conteneur..."
if ! docker compose up -d --remove-orphans; then
  restore_previous_version
  fail "demarrage du conteneur echoue pour le tag $target_tag${current_tag:+ — $current_tag remis en service}"
fi

# --- attente de la sante ------------------------------------------------------
log "attente du healthcheck (max ${HEALTH_TIMEOUT_SECONDS}s)..."
deadline=$(( SECONDS + HEALTH_TIMEOUT_SECONDS ))
health_state=""
while [ "$SECONDS" -lt "$deadline" ]; do
  container_id="$(docker compose ps -q "$SERVICE")"
  if [ -n "$container_id" ]; then
    health_state="$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || echo unknown)"
    case "$health_state" in
      healthy) break ;;
      unhealthy) break ;;
    esac
  fi
  sleep 3
done

if [ "$health_state" != "healthy" ]; then
  log "etat du conteneur: ${health_state:-inconnu}"
  docker compose logs --tail 50 "$SERVICE" || true
  restore_previous_version
  fail "conteneur non sain apres deploiement du tag $target_tag${current_tag:+ — $current_tag remis en service}"
fi

# --- succes : on memorise le tag precedent pour le rollback --------------------
if [ -n "$current_tag" ] && [ "$current_tag" != "$target_tag" ]; then
  write_env_key DEEZER_PREVIOUS_IMAGE_TAG "$current_tag"
fi

log "nettoyage des images orphelines..."
docker image prune -f >/dev/null || true

log "deploiement termine — tag actif: $target_tag"
docker compose ps
```

```bash
chmod +x deploy/deploy.sh
```

- [ ] **Step 4: Vérifier**

Run : les deux blocs de l'étape 1, puis `bash -n deploy/deploy.sh && uvx --from shellcheck-py shellcheck deploy/deploy.sh && echo shell-ok`.
Expected :
- cas 1 : `[deploy] ERREUR: .../state.json absent ...`, `exit=1`, `pas de state.json cree` ;
- cas 2 : `[deploy] ERREUR: pull de l'image echoue pour le tag tag-inexistant-sur-ghcr ...`, `exit=1`, `DEEZER_IMAGE_TAG=tag-precedent` ;
- `shell-ok`.

Le chemin de succès est vérifié en production (Task 9) : il demande une image publiée sur ghcr.

- [ ] **Step 5: Commit**

```bash
git add deploy/deploy.sh
git commit -q -F - <<'EOF'
deploy: pull-based deploy script with health check and automatic restore

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: Deezer, workflow et documentation

**Files:**
- Create: `.github/workflows/deploy.yml`
- Modify: `deploy/SETUP.md` (réécrit)
- Delete: `deploy/deezer-mix.service`, `deploy/deezer.beraud.dev.conf`

**Interfaces:**
- Consumes: commande de test (Task 2), `Dockerfile` (Task 3), `docker-compose.yml` et `.env.example` (Task 4), `deploy/deploy.sh` et son interface (Task 5), versions validées en Task 1.
- Produces: le workflow `Deploy` ; les secrets attendus (posés en Task 7).

- [ ] **Step 1: Écrire la vérification**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
check_workflow() {
  [ -f .github/workflows/deploy.yml ] || { echo "workflow absent"; return 1; }
  uvx --from actionlint-py actionlint .github/workflows/deploy.yml || return 1
  ! grep -nE 'ubuntu-latest|@v[0-9]+$' .github/workflows/deploy.yml | grep -vE 'checkout@v7|setup-buildx-action@v4|login-action@v4|build-push-action@v7'
  [ ! -e deploy/deezer-mix.service ] && [ ! -e deploy/deezer.beraud.dev.conf ] || { echo "fichiers obsoletes presents"; return 1; }
  ! grep -niE 'apache|certbot|systemd' deploy/SETUP.md
}
```

- [ ] **Step 2: Vérifier qu'elle échoue**

Run: `check_workflow; echo "exit=$?"`
Expected: `workflow absent`, `exit=1`.

- [ ] **Step 3: Écrire le workflow, la doc, et retirer l'obsolète**

`.github/workflows/deploy.yml` :

```yaml
name: Deploy

# Chaine de deploiement pull-based, calquee sur garmin-parser :
#   test -> build de l'image sur le runner GitHub -> push sur ghcr.io
#        -> le VPS tire l'image via deploy/deploy.sh
# Le VPS ne construit rien et ne recoit aucune source.

on:
  push:
    branches:
      - main
  workflow_dispatch:
    inputs:
      image_tag:
        description: "SHA deja publie sur ghcr a redeployer tel quel (sans test ni build). Vide = test + build du HEAD courant."
        required: false
        type: string

concurrency:
  group: production-deploy
  cancel-in-progress: false

env:
  IMAGE: ghcr.io/${{ github.repository_owner }}/deezer-merger

jobs:
  test:
    name: Tests et analyse
    # Redeployer un tag deja publie ne teste ni ne reconstruit rien : l'image a
    # ete validee a sa construction. Le job build, qui en depend, est saute.
    if: ${{ !inputs.image_tag }}
    runs-on: ubuntu-26.04
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up uv
        uses: astral-sh/setup-uv@v10.2.0
        with:
          version: "0.12.17"
          enable-cache: true
          cache-dependency-glob: uv.lock

      - name: Install dependencies
        # --locked echoue si uv.lock ne correspond plus a pyproject.toml : la CI
        # refuse une resolution silencieusement differente du lock.
        run: uv sync --locked

      - name: Tests
        run: uv run python -m unittest discover -s tests -t .

      - name: Audit des dependances
        run: |
          uv export --no-hashes --no-dev > /tmp/requirements.txt
          uvx pip-audit -r /tmp/requirements.txt

      - name: Validate compose file
        # Une erreur de reference ou de syntaxe ne doit pas etre decouverte sur
        # le VPS. Compose exige que l'env_file existe : on le cree depuis
        # l'exemple.
        run: |
          set -euo pipefail
          cp .env.example .env
          docker compose config --quiet
          rm -f .env

  build:
    name: Build et publication de l'image
    needs: test
    runs-on: ubuntu-26.04
    permissions:
      contents: read
      packages: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v4

      - name: Log in to GHCR
        uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v7
        with:
          context: .
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ github.sha }}
            ${{ env.IMAGE }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    name: Deploy to production host
    needs: build
    # Un build saute n'est admis que pour un redeploiement explicite : sur un
    # push, des tests en echec sautent aussi le build et doivent bloquer ici.
    if: ${{ !cancelled() && (needs.build.result == 'success' || (github.event_name == 'workflow_dispatch' && inputs.image_tag != '' && needs.build.result == 'skipped')) }}
    runs-on: ubuntu-26.04
    environment: production
    permissions:
      contents: read
      # Le GITHUB_TOKEN de ce job sert au VPS pour tirer l'image.
      packages: read
    env:
      DEPLOY_DIR: /opt/deezer-merger
      SSH_PORT: ${{ secrets.DEEZER_SSH_PORT || '22' }}
      SSH_HOST: ${{ secrets.DEEZER_HOST }}
      SSH_USER: ${{ secrets.DEEZER_USER }}
      IMAGE_TAG: ${{ inputs.image_tag || github.sha }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Configure SSH
        run: |
          set -euo pipefail
          install -m 700 -d ~/.ssh
          printf '%s\n' "${{ secrets.DEEZER_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -p "$SSH_PORT" "$SSH_HOST" >> ~/.ssh/known_hosts

      - name: Upload compose file and deploy script
        run: |
          set -euo pipefail
          # Seuls ces deux fichiers transitent : aucune source applicative.
          scp -i ~/.ssh/deploy_key -P "$SSH_PORT" \
            docker-compose.yml deploy/deploy.sh \
            "$SSH_USER@$SSH_HOST:$DEPLOY_DIR/"

      - name: Pull image and restart service
        env:
          # Jeton ephemere, expire avec le job : le VPS ne garde aucun jeton
          # ghcr permanent. Passe sur stdin, jamais en argument de commande.
          GHCR_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GHCR_USER: ${{ github.actor }}
        run: |
          set -euo pipefail
          printf '%s' "$GHCR_TOKEN" | ssh -i ~/.ssh/deploy_key -p "$SSH_PORT" "$SSH_USER@$SSH_HOST" \
            "chmod +x $DEPLOY_DIR/deploy.sh && GHCR_USER='$GHCR_USER' $DEPLOY_DIR/deploy.sh --ghcr-token-stdin '$IMAGE_TAG'"
```

`deploy/SETUP.md` :

````markdown
# Deploiement de Deezer Mix

## Chaine

Un push sur `main` declenche `.github/workflows/deploy.yml` :

1. **Tests et analyse** : `uv sync --locked`, tests unitaires, `pip-audit`,
   validation de `docker-compose.yml`.
2. **Build** : image `ghcr.io/breraud/deezer-merger:<sha>` (et `:latest`),
   construite sur le runner GitHub.
3. **Deploiement** : la CI copie `docker-compose.yml` et `deploy/deploy.sh`
   dans `/opt/deezer-merger` sur le VPS, puis lance
   `deploy.sh --ghcr-token-stdin <sha>` avec son jeton ghcr ephemere.
   Le script tire l'image, recree le conteneur, attend le healthcheck et
   remet la version precedente en service en cas d'echec.

Le VPS ne contient aucune source : seulement `.env`, `state.json`,
`docker-compose.yml` et `deploy.sh`.

## Secrets GitHub

Environnement `production` du depot :

| Secret | Valeur |
|---|---|
| `DEEZER_SSH_KEY` | cle privee de deploiement (ed25519, dediee a ce depot) |
| `DEEZER_HOST` | `beraud.dev` |
| `DEEZER_USER` | `debian` |
| `DEEZER_SSH_PORT` | facultatif, 22 par defaut |

## Preparation du VPS (une seule fois)

```bash
sudo mkdir -p /opt/deezer-merger && sudo chown debian:debian /opt/deezer-merger
cd /opt/deezer-merger
curl -fsSL https://raw.githubusercontent.com/breraud/deezer-merger/main/.env.example -o .env
nano .env && chmod 600 .env
# Etat applicatif : restaurer l'existant, ou partir d'un fichier vide.
touch state.json && sudo chown 10001:10001 state.json
docker network inspect proxy >/dev/null   # reseau de Traefik, deja present
```

Le conteneur tourne en uid 10001 : `state.json` doit lui appartenir.

## Operations

```bash
# Redeployer un tag deja publie, sans test ni build
gh workflow run deploy.yml -R breraud/deezer-merger -f image_tag=<sha>

# Revenir a la version precedente
ssh debian@beraud.dev /opt/deezer-merger/deploy.sh --rollback

# Etat et logs
ssh debian@beraud.dev 'cd /opt/deezer-merger && docker compose ps && docker compose logs --tail 100'
```

Ne jamais sonder `/api/status` pour verifier le service : cette route peut
regenerer le mix et republier la playlist Deezer. Utiliser `/`.

## Developpement local

```bash
uv sync
cp .env.example .env   # puis renseigner l'ARL et les playlists
uv run uvicorn main:app --reload --port 3457
uv run python -m unittest discover -s tests -t .
```
````

```bash
mkdir -p .github/workflows
git rm -q deploy/deezer-mix.service deploy/deezer.beraud.dev.conf
```

- [ ] **Step 4: Vérifier**

Run: `check_workflow; echo "exit=$?"`
Expected: aucune sortie d'actionlint ni de grep, `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml deploy/SETUP.md
git commit -q -F - <<'EOF'
ci: test, publish to ghcr and deploy on push to main

Replaces the Apache/systemd setup notes with the pull-based pipeline
documentation.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
EOF
```

Ne pas pousser `main` : le premier push déploie, il attend les Tasks 7 et 8.

---

### Task 7: Clé de déploiement et secrets GitHub

**Files:** aucun dans les dépôts.

**Interfaces:**
- Consumes: noms des secrets (Task 6).
- Produces: environnement `production` de `deezer-merger` avec `DEEZER_SSH_KEY`, `DEEZER_HOST`, `DEEZER_USER` ; clé publique autorisée pour `debian` sur le VPS.

- [ ] **Step 1: Générer la paire de clés (local)**

```bash
KEYDIR=$(mktemp -d)
ssh-keygen -q -t ed25519 -N "" -C "deezer-merger-deploy" -f "$KEYDIR/deploy_key"
```

- [ ] **Step 2: ⚠ Accord : autoriser la clé sur le VPS**

```bash
ssh debian@beraud.dev 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys' < "$KEYDIR/deploy_key.pub"
ssh -i "$KEYDIR/deploy_key" -o IdentitiesOnly=yes -o BatchMode=yes debian@beraud.dev 'echo cle-ok'
```

Expected: `cle-ok`.

- [ ] **Step 3: ⚠ Accord : créer l'environnement et poser les secrets**

```bash
gh api -X PUT repos/breraud/deezer-merger/environments/production >/dev/null
gh secret set DEEZER_SSH_KEY --env production -R breraud/deezer-merger < "$KEYDIR/deploy_key"
gh secret set DEEZER_HOST --env production -R breraud/deezer-merger --body beraud.dev
gh secret set DEEZER_USER --env production -R breraud/deezer-merger --body debian
gh secret list --env production -R breraud/deezer-merger
```

Expected: les trois secrets listés.

- [ ] **Step 4: Détruire la copie locale de la clé privée**

```bash
shred -u "$KEYDIR/deploy_key" && rm -rf "$KEYDIR"
```

---

### Task 8: Préparation du VPS

**Files:** aucun dans les dépôts.

**Interfaces:**
- Consumes: rien.
- Produces: `/opt/deezer-merger` appartenant à `debian`, `state.json` à l'uid 10001, `.env` en 600, sauvegarde `/opt/deezer-merger.bak-2026-09-26` ; empreinte de référence de `state.json`.

- [ ] **Step 1: Vérifier les prérequis (lecture seule)**

```bash
ssh debian@beraud.dev '
  set -e
  test -f /opt/deezer-merger/state.json && echo "state: fichier"
  docker image inspect deezer-merger-deezer-app >/dev/null && echo "ancienne image: presente"
  docker network inspect proxy >/dev/null && echo "reseau proxy: present"
  test ! -e /opt/deezer-merger.bak-2026-09-26 && echo "sauvegarde: nom libre"
'
```

Expected: les quatre lignes. Sinon, s'arrêter et le signaler.

- [ ] **Step 2: ⚠ Accord : sauvegarder puis changer les droits**

```bash
ssh debian@beraud.dev '
  set -euo pipefail
  sudo cp -a /opt/deezer-merger /opt/deezer-merger.bak-2026-09-26
  sudo chown -R debian:debian /opt/deezer-merger
  sudo chown 10001:10001 /opt/deezer-merger/state.json
  chmod 600 /opt/deezer-merger/.env
  sha256sum /opt/deezer-merger/state.json /opt/deezer-merger.bak-2026-09-26/state.json
'
```

`DEEZER_IMAGE_TAG` n'est volontairement **pas** ajouté au `.env` (voir « Écart assumé »).

- [ ] **Step 3: Vérifier**

```bash
ssh debian@beraud.dev '
  cd /opt/deezer-merger
  stat -c "%n %U(%u) %a" . .env state.json
  test -r .env && echo "env lisible par debian"
  docker ps --filter name=^deezer$ --format "{{.Names}} {{.Status}}"
'
```

Expected: les deux empreintes de l'étape 2 identiques (la noter comme référence) ; `.` et `.env` à `debian` (`.env` en `600`), `state.json` à l'uid `10001` (nom affiché `UNKNOWN`, normal : aucun compte n'a cet uid sur le VPS) ; `env lisible par debian` ; l'ancien conteneur `deezer` toujours `Up` (il tourne en root, les droits ne le gênent pas).

---

### Task 9: Premier déploiement

**Files:** aucun.

**Interfaces:**
- Consumes: tout ce qui précède.
- Produces: Deezer en production sur l'image ghcr ; `main` branche par défaut.

- [ ] **Step 1: Relever l'empreinte juste avant la bascule**

```bash
ssh debian@beraud.dev 'sha256sum /opt/deezer-merger/state.json'
```

- [ ] **Step 2: ⚠ Accord : pousser `main` (déploie) et en faire la branche par défaut**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
uv run python -m unittest discover -s tests -t . 2>&1 | tail -1   # OK
git push origin main
gh repo edit breraud/deezer-merger --default-branch main
```

- [ ] **Step 3: Suivre le run**

```bash
sleep 5
RUN=$(gh run list -R breraud/deezer-merger --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN" -R breraud/deezer-merger --exit-status --interval 20 >/dev/null; echo "run exit=$?"
for u in $(gh api "repos/breraud/deezer-merger/actions/runs/$RUN/jobs" --jq '.jobs[].check_run_url'); do
  gh api "$u/annotations" --jq '.[] | "\(.annotation_level): \(.message)"'
done
```

Expected: `run exit=0`, aucune annotation.

- [ ] **Step 4: Vérifier la production**

```bash
ssh debian@beraud.dev '
  cd /opt/deezer-merger
  docker compose ps --format "{{.Name}} {{.Image}} {{.Status}}"
  grep "^DEEZER_IMAGE_TAG=" .env
  docker compose logs deezer-app 2>&1 | grep -cE "Falling back to default state|Traceback" || true
  sha256sum state.json
  docker ps -a --filter name=^deezer$ --format "{{.Names}}"
'
curl -sS -o /dev/null -w 'deezer %{http_code}\n' https://deezer.beraud.dev/
curl -sS -o /dev/null -w 'garmin %{http_code}\n' https://garmin.beraud.dev/
```

Expected:
- `deezer-merger-deezer-app-1 ghcr.io/breraud/deezer-merger:<sha> Up ... (healthy)` ;
- `DEEZER_IMAGE_TAG=<sha>` ;
- `0` ligne suspecte ;
- empreinte identique à l'étape 1 (si elle diffère, vérifier dans les logs qu'une action utilisateur l'explique ; sinon, c'est un défaut à analyser) ;
- plus de conteneur `deezer` ;
- `deezer 200`, `garmin 200`.

- [ ] **Step 5: Seulement si le déploiement a échoué : retour manuel**

Aucun tag précédent n'existe, `deploy.sh` n'a rien restauré. Depuis le dossier vivant, pour garder le `state.json` courant :

```bash
ssh debian@beraud.dev '
  set -euo pipefail
  cd /opt/deezer-merger
  cp /opt/deezer-merger.bak-2026-09-26/docker-compose.yml docker-compose.yml
  docker compose up -d --remove-orphans
  docker ps --format "{{.Names}} {{.Image}} {{.Status}}" | grep deezer
'
curl -sS -o /dev/null -w 'deezer %{http_code}\n' https://deezer.beraud.dev/
```

L'ancienne image `deezer-merger-deezer-app` est réutilisée sans build ; l'ancien conteneur tourne en root et écrit donc `state.json`. Analyser ensuite l'échec avec superpowers:systematic-debugging avant toute nouvelle tentative.

---

### Task 10: Nettoyage et mémoire

**Files:**
- Modify: `/home/brehan/.claude/projects/-home-brehan-Documents-Projet-Perso-garmin-scrapper/memory/vps-production.md`
- Modify: `/home/brehan/.claude/projects/-home-brehan-Documents-Projet-Perso-garmin-scrapper/memory/MEMORY.md` (si le titre de la ligne change)

**Interfaces:**
- Consumes: une production validée (Task 9, étape 4).
- Produces: un VPS sans sources Deezer ; une seule branche `main`.

- [ ] **Step 1: ⚠ Accord : retirer les sources du VPS**

```bash
ssh debian@beraud.dev '
  set -euo pipefail
  cd /opt/deezer-merger
  ls -A
  rm -rf .git .dockerignore .env.example .gitignore Dockerfile deezer_client.py deploy docs main.py requirements.txt static tests
  ls -A
'
```

Expected : il ne reste que `.env`, `deploy.sh`, `docker-compose.yml`, `state.json`. Toutes les sources sont dans la sauvegarde.

- [ ] **Step 2: ⚠ Accord : supprimer la branche `deploy/docker-prod`**

```bash
cd /home/brehan/Documents/Projet_Perso/deezer_sync
git push origin --delete deploy/docker-prod
git branch -d deploy/docker-prod
git branch -a
```

Expected : seules `main` et `origin/main` restent.

- [ ] **Step 3: Mettre à jour la mémoire**

Dans `vps-production.md`, ajouter : Deezer Mix est déployé en pull-based depuis 2026-09-26 (`/opt/deezer-merger`, projet compose `deezer-merger`, image `ghcr.io/breraud/deezer-merger`, conteneur non-root uid 10001 propriétaire de `state.json`) ; ne jamais sonder `/api/status` (republie la playlist) ; la sauvegarde `/opt/deezer-merger.bak-2026-09-26` et l'image `deezer-merger-deezer-app` restent jusqu'à décision de l'utilisateur.

- [ ] **Step 4: Rendre compte**

Résumer à l'utilisateur : runs Garmin et Deezer (liens), tags actifs, empreinte de `state.json`, et ce qui reste à décider (suppression de la sauvegarde et de l'ancienne image).
