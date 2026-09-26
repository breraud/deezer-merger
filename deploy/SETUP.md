# Deploiement de Deezer Mix

## Chaine

Un push sur `main` declenche `.github/workflows/deploy.yml` :

1. **Tests et analyse** : `uv sync --locked`, tests unitaires, `pip-audit`,
   validation de `docker-compose.yml`.
2. **Build** : image `ghcr.io/breraud/deezer-merger:<sha>` (et `:latest`),
   construite sur le runner GitHub.
3. **Deploiement** : la CI depose `docker-compose.yml` sous le nom
   `docker-compose.next.yml` et `deploy/deploy.sh` dans `/opt/deezer-merger`
   sur le VPS, puis lance `deploy.sh --ghcr-token-stdin <sha>` avec son jeton
   ghcr ephemere. Le script installe la nouvelle compose, tire l'image,
   recree le conteneur et attend le healthcheck. En cas d'echec, il remet en
   service la version precedente AVEC sa compose, verifie qu'elle est saine
   et le dit. Apres un succes, il ne garde que l'image active et celle du
   rollback.

Le VPS ne contient aucune source : seulement `.env`, `state.json`,
`docker-compose.yml` (version active), `docker-compose.previous.yml`
(version precedente, pour le rollback) et `deploy.sh`.

## Secrets GitHub

Environnement `production` du depot, reserve a la branche `main` : un
`workflow_dispatch` lance depuis une autre branche ne peut ni lire la cle ni
deployer.

| Secret | Valeur |
|---|---|
| `DEEZER_SSH_KEY` | cle privee de deploiement (ed25519, dediee a ce depot) |
| `DEEZER_HOST` | `beraud.dev` |
| `DEEZER_USER` | `debian` |
| `DEEZER_KNOWN_HOSTS` | ligne `known_hosts` de la cle d'hote ed25519 du VPS, verifiee contre un `known_hosts` de confiance |
| `DEEZER_SSH_PORT` | facultatif, 22 par defaut |

Pour regenerer `DEEZER_KNOWN_HOSTS` (changement de cle d'hote) :

```bash
ssh-keyscan -t ed25519 beraud.dev > kh && ssh-keygen -lf kh   # comparer l'empreinte
gh secret set DEEZER_KNOWN_HOSTS --env production -R breraud/deezer-merger < kh
```

## Preparation du VPS (une seule fois)

```bash
sudo mkdir -p /opt/deezer-merger && sudo chown debian:debian /opt/deezer-merger
cd /opt/deezer-merger
# umask 077 : .env (qui recevra l'ARL) est cree en 600, jamais lisible par
# les autres comptes du VPS partage, meme un instant.
(umask 077 && curl -fsSL https://raw.githubusercontent.com/breraud/deezer-merger/main/.env.example -o .env)
nano .env
# Etat applicatif : restaurer l'existant, ou partir d'un fichier vide.
touch state.json && sudo chown 10001:10001 state.json
docker network inspect proxy >/dev/null   # reseau de Traefik, deja present
```

Le conteneur tourne en uid 10001 : `state.json` doit lui appartenir, et
`deploy.sh` refuse de deployer sinon. Apres une edition a la main (`sudo`),
le rendre a son proprietaire : `sudo chown 10001:10001 state.json`.

## Operations

```bash
# Redeployer un tag deja publie, sans test ni build
gh workflow run deploy.yml -R breraud/deezer-merger -f image_tag=<sha>

# Revenir a la version precedente (image et compose, sans jeton ghcr). La
# version quittee n'est pas retenue : un second --rollback est refuse.
ssh debian@beraud.dev /opt/deezer-merger/deploy.sh --rollback

# Revenir explicitement a une version precise (dont celle quittee par un
# rollback, gardee sur le VPS jusqu'au deploiement suivant)
ssh debian@beraud.dev /opt/deezer-merger/deploy.sh <sha>

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
