#!/usr/bin/env bash
#
# Deploiement pull-based de Deezer Mix sur le VPS.
#
#   ./deploy.sh <tag>       deploie le tag demande (SHA de commit, ou `latest`)
#   ./deploy.sh             redeploie le tag actuellement enregistre
#   ./deploy.sh --rollback  revient au tag deploye precedemment, avec sa compose.
#                           La version quittee n'est pas retenue : un second
#                           --rollback est refuse, `./deploy.sh <tag>` y revient.
#
#   --ghcr-token-stdin, en premier argument : lit sur stdin le jeton ghcr que
#   la CI transmet (son GITHUB_TOKEN ephemere, avec GHCR_USER dans l'env).
#
# Le VPS ne construit aucune image : elle est produite par la CI et tiree
# depuis ghcr.io. Ce script est remplace a chaque deploiement par la CI, donc
# toute modification doit se faire dans le depot (deploy/deploy.sh).
#
# Composes, dans $DEPLOY_DIR :
#   - docker-compose.yml           celle de la version qui tourne ;
#   - docker-compose.next.yml      deposee par la CI, installee par ce script ;
#   - docker-compose.previous.yml  celle de la version precedente (--rollback).
# En cas d'echec, la version precedente repart avec SA compose : la CI a deja
# depose la nouvelle, qui peut etre la cause de l'echec.
#
# Pre-requis, une seule fois sur le VPS (voir deploy/SETUP.md) :
#   - /opt/deezer-merger/.env        variables Deezer (chmod 600)
#   - /opt/deezer-merger/state.json  etat applicatif, proprietaire uid 10001
#   - /opt/deezer-merger/.ghcr.env   GHCR_USER=... / GHCR_TOKEN=... (chmod 600)
#     seulement pour tirer a la main une image absente de l'hote si elle
#     devient privee (elle est publique aujourd'hui) : la CI fournit son propre
#     jeton, et --rollback reutilise l'image deja presente.

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/deezer-merger}"
ENV_FILE="$DEPLOY_DIR/.env"
STATE_FILE="$DEPLOY_DIR/state.json"
GHCR_ENV_FILE="$DEPLOY_DIR/.ghcr.env"
NEXT_COMPOSE="docker-compose.next.yml"
PREVIOUS_COMPOSE="docker-compose.previous.yml"
SERVICE="deezer-app"
IMAGE_REPO="ghcr.io/breraud/deezer-merger"
# Utilisateur du conteneur (Dockerfile) : il doit pouvoir ecrire state.json.
STATE_UID="${STATE_UID:-10001}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-120}"

log() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy] ERREUR: %s\n' "$*" >&2; exit 1; }

cd "$DEPLOY_DIR" || fail "repertoire de deploiement introuvable: $DEPLOY_DIR"
[ -f docker-compose.yml ] || [ -f "$NEXT_COMPOSE" ] \
  || fail "ni docker-compose.yml ni $NEXT_COMPOSE dans $DEPLOY_DIR"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE absent (requis par compose et par l'application)"
# Monte en bind : absent, docker creerait un repertoire a sa place et
# l'application repartirait d'un etat vide, rechargee depuis Deezer.
[ -f "$STATE_FILE" ] || fail "$STATE_FILE absent : restaurer l'etat, ou creer un fichier vide appartenant a l'uid $STATE_UID"
# Lisible mais pas inscriptible, le conteneur resterait sain, puis « Generer »
# publierait la playlist Deezer sans pouvoir enregistrer l'etat.
[ "$(stat -c %u "$STATE_FILE")" = "$STATE_UID" ] \
  || fail "$STATE_FILE doit appartenir a l'uid $STATE_UID (utilisateur du conteneur) : sudo chown $STATE_UID:$STATE_UID $STATE_FILE"

# --- lecture d'une cle dans le .env ------------------------------------------
read_env_key() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

# --- suppression d'une cle du .env ---------------------------------------------
delete_env_key() {
  local key="$1" tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
  chmod --reference="$ENV_FILE" "$tmp"
  mv "$tmp" "$ENV_FILE"
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
rollback=0

if [ "$#" -eq 0 ]; then
  [ -n "$current_tag" ] || fail "aucun tag enregistre et aucun tag fourni en argument"
  target_tag="$current_tag"
elif [ "$1" = --rollback ]; then
  [ -n "$previous_tag" ] \
    || fail "aucun tag precedent enregistre, rollback impossible : redeployer une version precise avec ./deploy.sh <tag>"
  target_tag="$previous_tag"
  rollback=1
  log "rollback demande vers $target_tag"
else
  target_tag="$1"
fi

# Grammaire d'un tag docker. Le tag vient d'une saisie (workflow_dispatch) et
# finit dans .env et dans des commandes : une quote ou un saut de ligne les
# casserait.
[[ "$target_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] \
  || fail "tag invalide : '$target_tag' (attendu : SHA de commit ou latest)"

log "tag cible      : $target_tag"
log "tag courant    : ${current_tag:-<aucun>}"

# --- fichiers temporaires -----------------------------------------------------
# Les identifiants ghcr vivent dans un DOCKER_CONFIG propre a ce deploiement,
# detruit en sortie. ~/.docker/config.json est partage avec les autres projets
# du VPS : le runner d'insastronaute y fait `docker logout ghcr.io`.
DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG
running_compose=""
trap 'rm -rf "$DOCKER_CONFIG" ${running_compose:+"$running_compose"}' EXIT

# --- authentification ghcr ----------------------------------------------------
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

# --- installation de la compose cible ------------------------------------------
# On garde une copie de la compose qui tourne : c'est avec elle que la version
# courante repartira si la cible echoue.
if [ -f docker-compose.yml ]; then
  running_compose="$(mktemp "$DEPLOY_DIR/.compose-running.XXXXXX")"
  cp docker-compose.yml "$running_compose"
fi

if [ "$rollback" = 1 ] && [ -f "$PREVIOUS_COMPOSE" ]; then
  cp "$PREVIOUS_COMPOSE" docker-compose.yml
elif [ "$rollback" = 0 ] && [ -f "$NEXT_COMPOSE" ]; then
  # Consommee ici : un redeploiement manuel ulterieur ne doit pas installer la
  # compose d'une version qui a echoue.
  mv "$NEXT_COMPOSE" docker-compose.yml
fi

# --- pull avant bascule -------------------------------------------------------
# On ecrit le tag AVANT le pull pour que compose resolve la bonne image, mais
# on conserve l'ancien pour pouvoir revenir en arriere si le pull ou la sante
# echouent.
write_env_key DEEZER_IMAGE_TAG "$target_tag"

restore_previous_config() {
  if [ -n "$running_compose" ]; then
    cp "$running_compose" docker-compose.yml
  fi
  if [ -n "$current_tag" ]; then
    log "restauration du tag $current_tag dans $ENV_FILE"
    write_env_key DEEZER_IMAGE_TAG "$current_tag"
  else
    # Premier deploiement : aucun tag a restaurer, mais celui de la version
    # ratee ne doit pas rester, le suivant la retiendrait pour le rollback.
    delete_env_key DEEZER_IMAGE_TAG
  fi
}

# Attend le verdict du healthcheck et l'affiche : healthy, unhealthy, ou
# l'etat atteint a l'expiration du delai.
wait_for_health() {
  local deadline=$(( SECONDS + HEALTH_TIMEOUT_SECONDS )) state="" container_id
  while [ "$SECONDS" -lt "$deadline" ]; do
    container_id="$(docker compose ps -q "$SERVICE")"
    if [ -n "$container_id" ]; then
      state="$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || echo unknown)"
      case "$state" in
        healthy|unhealthy) break ;;
      esac
    fi
    sleep 3
  done
  printf '%s' "${state:-inconnu}"
}

# Une fois le conteneur recree, restaurer la configuration ne suffit plus : il
# faut remettre en service la version qui tournait, et verifier qu'elle est
# saine avant de l'annoncer. --rollback n'est pas une issue, il vise le tag
# d'AVANT celui-ci. Le resultat est range dans restore_outcome.
restore_previous_version() {
  local state
  restore_previous_config
  if [ -z "$current_tag" ]; then
    restore_outcome="aucune version precedente a remettre en service"
    return
  fi
  log "remise en service de $current_tag..."
  if ! docker compose up -d --remove-orphans; then
    restore_outcome="remise en service de $current_tag echouee, relancer './deploy.sh $current_tag'"
    return
  fi
  state="$(wait_for_health)"
  if [ "$state" = healthy ]; then
    restore_outcome="$current_tag remis en service"
  else
    restore_outcome="$current_tag redemarre mais non sain ($state) : intervention manuelle requise"
  fi
}

# Un tag de commit designe toujours la meme image : deja sur l'hote (cas du
# rollback), inutile de la retirer, et le rollback ne depend alors ni d'un
# jeton ghcr ni de la disponibilite du registre. `latest` bouge : toujours tire.
if [ "$target_tag" != latest ] && docker image inspect "$IMAGE_REPO:$target_tag" >/dev/null 2>&1; then
  log "image $target_tag deja presente sur l'hote, pas de pull"
else
  log "pull de l'image..."
  if ! docker compose pull; then
    restore_previous_config
    fail "pull de l'image echoue pour le tag $target_tag (tag inexistant ou acces ghcr refuse)"
  fi
fi

log "recreation du conteneur..."
if ! docker compose up -d --remove-orphans; then
  restore_previous_version
  fail "demarrage du conteneur echoue pour le tag $target_tag — $restore_outcome"
fi

log "attente du healthcheck (max ${HEALTH_TIMEOUT_SECONDS}s)..."
health_state="$(wait_for_health)"
if [ "$health_state" != healthy ]; then
  log "etat du conteneur: $health_state"
  docker compose logs --tail 50 "$SERVICE" || true
  restore_previous_version
  fail "conteneur non sain apres deploiement du tag $target_tag — $restore_outcome"
fi

# --- succes : on memorise la version precedente pour le rollback ---------------
if [ "$rollback" = 1 ]; then
  # La version quittee est jugee mauvaise : pas de retour implicite par un
  # second --rollback. Son image reste jusqu'au prochain deploiement, pour un
  # `./deploy.sh <tag>` explicite.
  delete_env_key DEEZER_PREVIOUS_IMAGE_TAG
  rm -f "$PREVIOUS_COMPOSE"
elif [ -n "$current_tag" ] && [ "$current_tag" != "$target_tag" ]; then
  write_env_key DEEZER_PREVIOUS_IMAGE_TAG "$current_tag"
  if [ -n "$running_compose" ]; then
    cp "$running_compose" "$PREVIOUS_COMPOSE"
  fi
fi

# Le disque du VPS est partage : on ne garde que la version active et celle du
# rollback. Une image encore utilisee refuse d'etre supprimee, sans dommage.
log "nettoyage des anciennes images..."
docker image ls "$IMAGE_REPO" --format '{{.Tag}}' | while IFS= read -r tag; do
  case "$tag" in
    "$target_tag"|"$current_tag"|"") continue ;;
  esac
  docker image rm "$IMAGE_REPO:$tag" >/dev/null 2>&1 || true
done
docker image prune -f >/dev/null || true

log "deploiement termine — tag actif: $target_tag"
docker compose ps
