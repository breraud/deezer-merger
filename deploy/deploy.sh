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
