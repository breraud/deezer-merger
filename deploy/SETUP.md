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
