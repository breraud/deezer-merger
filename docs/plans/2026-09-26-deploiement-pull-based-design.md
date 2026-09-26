# Déploiement pull-based de Deezer Mix, aligné sur Garmin

Date : 2026-09-26. Statut : design validé en conversation, en attente de relecture.

## Contexte

Deezer Mix tourne sur le VPS partagé `beraud.dev` (celui de Garmin), derrière
Traefik, sous le nom `deezer.beraud.dev`. Son déploiement est entièrement
manuel :

- `/opt/deezer-merger` est un clone Git du 8 juin, propriété de `root`.
- L'image est construite sur le VPS (`build: .`) par une `docker-compose.yml`
  modifiée à la main (labels Traefik, réseau `proxy`), différente de celle du
  dépôt.
- Aucun healthcheck, aucune CI, aucun rollback.
- `state.json` (état applicatif, écrit par l'application) et `.env` (dont
  l'ARL Deezer) sont montés depuis ce dossier : ce sont les seules données à
  préserver.
- La doc `deploy/` du dépôt décrit une installation Apache + certbot + systemd
  qui ne correspond plus à la réalité.
- La branche par défaut sur GitHub est `deploy/docker-prod`, en avance de deux
  commits sur `main`.

Garmin (`breraud/garmin-parser`) a depuis le 2026-09-24 une chaîne
pull-based : tests en CI, images publiées sur ghcr.io, le VPS tire l'image
via `deploy/deploy.sh` avec healthcheck et remise en service automatique de la
version précédente. Son dernier run (2026-09-26) affiche des avertissements :
actions en Node 20 dépréciées, et `ubuntu-latest` qui basculera vers
Ubuntu 26 le 2026-10-19.

## Objectif

1. Donner à Deezer la même chaîne de déploiement que Garmin.
2. Mettre les workflows des deux projets sur des actions et un runner à jour,
   pour que leurs runs ne produisent plus d'avertissement.

Critères de succès :

- Un push sur `main` de `deezer-merger` teste, publie l'image et la déploie
  sans intervention.
- `deezer.beraud.dev` répond 200 après la bascule ; le conteneur est `healthy`.
- `state.json` a le même SHA-256 avant et après la bascule.
- Le VPS ne contient plus aucune source de Deezer.
- Les runs Garmin et Deezer ne contiennent aucun avertissement de dépréciation
  ni de migration de runner.

## Décisions

| Sujet | Décision | Raison |
|---|---|---|
| Partage avec Garmin | Copie adaptée dans chaque dépôt | Dépôts autonomes ; un changement de l'un ne touche pas la prod de l'autre. |
| Dépendances | Migration vers uv : `pyproject.toml` + `uv.lock` | Parité avec Garmin ; l'image embarque exactement les versions testées. |
| Python | 3.12 (image `trixie-slim`) | Aligné sur le backend Garmin. |
| Utilisateur du conteneur | Non-root, uid 10001 | Aligné sur Garmin ; `state.json` est rendu inscriptible pour cet uid. |
| Healthcheck | `GET /` | `/api/status` peut appeler `generate_mix` et republier la playlist Deezer : inutilisable comme sonde. |
| Branche de déploiement | `main` | `main` rattrape `deploy/docker-prod` en fast-forward et devient la branche par défaut. |
| Dossier sur le VPS | `/opt/deezer-merger` (inchangé) | Même projet compose `deezer-merger` : la bascule remplace le conteneur existant. |
| Image | `ghcr.io/breraud/deezer-merger:<sha>` et `:latest` | Même convention que Garmin. |
| Actions GitHub | `checkout@v7`, `setup-node@v7`, `setup-buildx-action@v4`, `login-action@v4`, `build-push-action@v7`, `setup-uv@v10.2.0` | Dernières versions majeures, toutes en Node 24. `setup-uv` ne publie plus de tag majeur flottant : version exacte. |
| Runner | `ubuntu-26.04`, épinglé | Cible de la bascule de `ubuntu-latest` ; l'épingler supprime l'avis et évite une migration surprise. |

## Dépôt deezer-merger

### Fichiers

- `pyproject.toml` : projet non empaqueté (`[tool.uv] package = false`),
  `requires-python = ">=3.12"`, dépendances avec les versions actuelles comme
  minimum : `fastapi>=0.136.0`, `uvicorn>=0.46.0`, `deezer-python-gql>=0.9.0`,
  `python-dotenv>=1.2.2`.
- `uv.lock` : généré par `uv lock`, versionné.
- `requirements.txt` : supprimé.
- `Dockerfile` : deux étapes, calquées sur `garmin-parser/backend/Dockerfile`.
  - `ghcr.io/astral-sh/uv:0.12-python3.12-trixie-slim` installe les
    dépendances (`uv sync --locked --no-dev`) dans `/app/.venv`.
  - `python:3.12-slim-trixie` reçoit le venv, `main.py`, `deezer_client.py` et
    `static/`, tourne en `appuser` (uid 10001), expose 3457,
    `uvicorn main:app --host 0.0.0.0 --port 3457`.
- `.dockerignore` : exclut en plus `tests/`, `docs/`, `deploy/`, `.github/`.
- `docker-compose.yml` : compose de production uniquement.
  - Service `deezer-app`, image
    `ghcr.io/breraud/deezer-merger:${DEEZER_IMAGE_TAG:-latest}`.
  - `env_file: ./.env`, `STATE_FILE_PATH=/app/state.json`, volume
    `./state.json:/app/state.json`. Le montage de `.env` dans le conteneur
    disparaît : `env_file` suffit.
  - Réseau externe `proxy`, aucun port publié.
  - Healthcheck par l'interpréteur Python (l'image n'a ni curl ni wget) sur
    `http://127.0.0.1:3457/`.
  - Labels Traefik : routeur `deezer` sur ``Host(`deezer.beraud.dev`)``,
    port 3457, `traefik.docker.network=proxy`.
  - Plus de `container_name` : le conteneur prend le nom standard de compose.
- `.env.example` : variables Deezer existantes + `DEEZER_IMAGE_TAG=latest`.
- `deploy/deploy.sh` : copie de celui de Garmin, adaptée :
  `DEPLOY_DIR=/opt/deezer-merger`, clés `DEEZER_IMAGE_TAG` et
  `DEEZER_PREVIOUS_IMAGE_TAG`, healthcheck sur le service `deezer-app`,
  même gestion du jeton ghcr éphémère (lu sur stdin, `DOCKER_CONFIG`
  temporaire), même remise en service de la version précédente, `--rollback`.
- `deploy/SETUP.md` : réécrit pour la chaîne pull-based (secrets GitHub,
  préparation unique du VPS, redéploiement, rollback).
- `deploy/deezer-mix.service` et `deploy/deezer.beraud.dev.conf` : supprimés
  (systemd et Apache ne sont plus utilisés).

### Workflow `.github/workflows/deploy.yml`

Déclenché par un push sur `main` et par `workflow_dispatch` (entrée
`image_tag` pour redéployer un tag déjà publié sans test ni build).
Concurrence `production-deploy`, sans annulation.

1. `test` : `uv sync --locked`, tests
   (`uv run python -m unittest discover -s tests -t .`), audit
   (`uv export --no-hashes --no-dev` puis `uvx pip-audit`), validation de la
   compose (`cp .env.example .env && docker compose config --quiet`).
2. `build` : Buildx, connexion à ghcr avec `GITHUB_TOKEN`, build et push de
   `:<sha>` et `:latest`, cache `type=gha`.
3. `deploy` : environnement `production`. Envoi de `docker-compose.yml` et
   `deploy/deploy.sh` par `scp`, puis `deploy.sh --ghcr-token-stdin <tag>` par
   SSH avec le `GITHUB_TOKEN` du job sur stdin. Secrets : `DEEZER_SSH_KEY`,
   `DEEZER_HOST`, `DEEZER_USER`, `DEEZER_SSH_PORT` (facultatif, 22 par défaut).

Tous les jobs tournent sur `ubuntu-26.04` avec les versions d'actions du
tableau des décisions.

### Développement local

`uv sync` puis `uv run uvicorn main:app --reload --port 3457`. La compose du
dépôt ne sert plus qu'à la production.

## Dépôt garmin-parser

Seul `.github/workflows/deploy.yml` change : `runs-on: ubuntu-26.04` et
versions d'actions du tableau des décisions. Les entrées utilisées restent
valables (`setup-uv` : `version`, `enable-cache: true` explicite, donc non
concerné par la désactivation du cache par défaut de la v10 ;
`setup-node` : `node-version`, `cache`, `cache-dependency-path`). Le push
sur `main` redéploie Garmin à l'identique : c'est le test du changement.

## Bascule du VPS

Écritures sur un VPS partagé : chaque étape est confirmée avant exécution.

1. **Clé de déploiement** : une paire ed25519 dédiée à Deezer. Clé publique
   ajoutée à `~debian/.ssh/authorized_keys` ; clé privée, hôte et utilisateur
   posés en secrets de l'environnement `production` de `deezer-merger`.
2. **Sauvegarde** : `cp -a /opt/deezer-merger /opt/deezer-merger.bak-2026-09-26`,
   et relevé du SHA-256 de `state.json`.
3. **Droits** : `/opt/deezer-merger` passe à `debian:debian` ; `state.json`
   passe à l'uid 10001, inscriptible par le conteneur non-root. `.env`
   (qui contient l'ARL) passe en 600 : seul `debian`, qui lance compose, le
   lit. `DEEZER_IMAGE_TAG` est ajouté au `.env`.
4. **Premier déploiement** : push sur `main`. `deploy.sh` tire l'image et
   recrée le service `deezer-app` du projet `deezer-merger` : l'ancien
   conteneur `deezer` est remplacé. Coupure de quelques secondes.
5. **Si le premier déploiement échoue** : aucun tag précédent n'existe, donc
   pas de remise en service automatique. Retour manuel, depuis le dossier
   vivant pour garder le `state.json` courant (pas la copie de la
   sauvegarde) : remettre l'ancienne compose
   (`cp /opt/deezer-merger.bak-2026-09-26/docker-compose.yml /opt/deezer-merger/`)
   puis `docker compose up -d --remove-orphans`. L'image locale
   `deezer-merger-deezer-app` existe toujours (`deploy.sh` ne supprime que les
   images orphelines, pas les images nommées) : compose la réutilise sans
   build. L'ancien conteneur tourne en root et écrit donc toujours
   `state.json`.
6. **Après validation** : les sources (`main.py`, `static/`, `.git`, etc.)
   sont retirées de `/opt/deezer-merger` ; restent `.env`, `state.json`,
   `docker-compose.yml`, `deploy.sh`. La sauvegarde et l'ancienne image sont
   gardées jusqu'à ce que tu décides de les supprimer.

## GitHub

- `main` avancée en fast-forward sur `deploy/docker-prod`, puis branche par
  défaut de `deezer-merger` ; `deploy/docker-prod` supprimée une fois la
  bascule validée.
- Environnement `production` créé dans `deezer-merger`, avec les secrets
  ci-dessus.
- Le paquet ghcr `deezer-merger` est créé par le premier build ; le VPS le
  tire avec le jeton éphémère du job, quelle que soit sa visibilité.

## Vérification

- Local : `uv sync --locked`, les 21 tests, `docker build`, conteneur lancé
  avec un `state.json` de test jusqu'à `healthy`, `GET /` à 200, écriture de
  `state.json` possible par l'uid 10001.
- CI : run Deezer vert de bout en bout ; run Garmin vert ; aucun avertissement
  Node 20 ni de migration de runner dans les deux.
- Prod : `deezer.beraud.dev` à 200, conteneur `healthy` sur le bon tag,
  SHA-256 de `state.json` inchangé, `garmin.beraud.dev` toujours sain.

## Hors périmètre

- Socle de déploiement commun aux deux dépôts.
- Ruff et mypy pour Deezer.
- Suppression de la sauvegarde et de l'ancienne image sur le VPS.
