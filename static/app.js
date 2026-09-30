// Interface de Deezer Mix. Tout texte venant de Deezer (titres, artistes, noms
// de playlist) passe par textContent : un titre contenant du HTML reste du
// texte.

const PLAYER_IDS = ["player1", "player2", "player3"];
const BALANCED_STORAGE_KEY = "deezer-mix-balanced";

const syncBadge = document.querySelector("#sync-badge");
const statusMessage = document.querySelector("#status-message");
const mixList = document.querySelector("#mix-list");
const mixCount = document.querySelector("#mix-count");
const duplicatesPanel = document.querySelector("#duplicates");
const duplicatesTitle = duplicatesPanel.querySelector('[data-role="title"]');
const duplicatesHint = duplicatesPanel.querySelector('[data-role="hint"]');
const duplicateList = document.querySelector("#duplicate-list");
const balancedToggle = document.querySelector("#balanced-toggle");
const generateButton = document.querySelector("#generate-button");
const resetButton = document.querySelector("#reset-button");
const resetConfirm = document.querySelector("#reset-confirm");
const resetConfirmButton = document.querySelector("#reset-confirm-button");
const resetCancelButton = document.querySelector("#reset-cancel-button");
const actionButtons = Array.from(document.querySelectorAll("main button"));

const cards = Object.fromEntries(
  PLAYER_IDS.map((playerId) => {
    const card = document.querySelector(`.player-card[data-player="${playerId}"]`);
    return [
      playerId,
      {
        name: card.querySelector('[data-role="name"]'),
        meta: card.querySelector('[data-role="meta"]'),
        tracks: card.querySelector('[data-role="tracks"]'),
        button: card.querySelector('[data-action="refresh"]'),
      },
    ];
  }),
);

let playerNames = Object.fromEntries(
  PLAYER_IDS.map((playerId, index) => [playerId, `Playlist ${index + 1}`]),
);

// --- utilitaires -------------------------------------------------------------

function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count} ${count > 1 ? pluralForm : singular}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function trackTitle(track) {
  return track.title || `Titre inconnu (${track.id || "?"})`;
}

function trackArtist(track) {
  return track.artist || "Artiste inconnu";
}

// --- messages ----------------------------------------------------------------

function setBadge(state, text) {
  syncBadge.dataset.state = state;
  syncBadge.textContent = text;
}

function showNotice(tone, text) {
  statusMessage.replaceChildren();
  statusMessage.dataset.tone = tone;
  // Une erreur doit etre annoncee tout de suite ; le reste peut attendre.
  statusMessage.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
  if (tone === "error") statusMessage.appendChild(icon("warning"));
  if (tone === "success") statusMessage.appendChild(icon("check"));
  statusMessage.appendChild(el("span", "", text));
  statusMessage.hidden = false;
}

function hideNotice() {
  statusMessage.hidden = true;
  statusMessage.replaceChildren();
}

// --- rendu -------------------------------------------------------------------

function indexOwners(listsByPlayer) {
  const index = new Map();
  for (const playerId of PLAYER_IDS) {
    for (const track of listsByPlayer[playerId] || []) {
      if (!track?.id) continue;
      const owners = index.get(track.id) || [];
      if (!owners.includes(playerId)) owners.push(playerId);
      index.set(track.id, owners);
    }
  }
  return index;
}

// Les playlists d'origine d'un titre : les selections publiees, a defaut le
// cache des sources. Un titre partage n'est qu'une fois dans le mix, avec
// toutes ses playlists.
function buildSourceIndex(players, sourcePools) {
  const selections = Object.fromEntries(PLAYER_IDS.map((playerId) => [playerId, players[playerId]?.selection]));
  const index = indexOwners(sourcePools);
  for (const [trackId, owners] of indexOwners(selections)) index.set(trackId, owners);
  return index;
}

function sourceChips(playerIds) {
  const chips = el("span", "source-chips");
  for (const playerId of playerIds) {
    const chip = el("span", "source-chip", playerNames[playerId]);
    chip.dataset.source = playerId;
    chips.appendChild(chip);
  }
  return chips;
}

function renderDuplicates(duplicates) {
  duplicatesPanel.hidden = duplicates.length === 0;
  duplicatesTitle.textContent = `${plural(duplicates.length, "titre")} dans plusieurs playlists`;
  duplicatesHint.textContent = duplicates.length > 1
    ? "Ils ne figurent qu’une fois dans le mix."
    : "Il ne figure qu’une fois dans le mix.";
  duplicateList.replaceChildren(
    ...duplicates.map((track) => {
      const item = el("li", "duplicate-item");
      const body = el("span", "track");
      body.appendChild(el("span", "track-title", trackTitle(track)));
      body.appendChild(el("span", "track-artist", trackArtist(track)));
      item.append(body, sourceChips(track.players || []));
      return item;
    }),
  );
}

function renderMix(mix, sourceIndex, hasLoadedSources) {
  mixCount.textContent = plural(mix.length, "titre");

  if (mix.length === 0) {
    const empty = el("li", "empty-state");
    empty.appendChild(el("strong", "", hasLoadedSources ? "Le mix est vide." : "Aucune playlist chargée."));
    empty.appendChild(
      el(
        "span",
        "",
        hasLoadedSources
          ? "Génère un nouveau mix pour remplir la playlist cible."
          : "Ouvre « Avancé » et lance la réinitialisation pour le premier chargement.",
      ),
    );
    mixList.replaceChildren(empty);
    return;
  }

  const items = mix.map((track, position) => {
    const item = el("li", "mix-item");
    item.appendChild(el("span", "mix-rank", String(position + 1)));
    const body = el("span", "track");
    body.appendChild(el("span", "track-title", trackTitle(track)));
    body.appendChild(el("span", "track-artist", trackArtist(track)));
    item.appendChild(body);
    const sources = sourceIndex.get(track.id);
    if (sources) item.appendChild(sourceChips(sources));
    return item;
  });
  mixList.replaceChildren(...items);
}

function renderPlayers(players, sourcePools) {
  for (const playerId of PLAYER_IDS) {
    const card = cards[playerId];
    const pool = sourcePools[playerId] || [];
    const name = players[playerId]?.name || playerNames[playerId];
    playerNames[playerId] = name;
    // La selection publiee : un titre partage compte pour chacune de ses playlists.
    const inMix = players[playerId]?.selection?.length ?? 0;

    card.name.textContent = name;
    card.button.setAttribute("aria-label", `Rafraîchir ${name}`);
    card.meta.textContent =
      pool.length === 0
        ? "Aucun titre chargé."
        : `${plural(inMix, "titre")} dans le mix sur ${pool.length} chargé${pool.length > 1 ? "s" : ""}`;

    if (pool.length === 0) {
      card.tracks.replaceChildren(el("li", "empty", "Aucun titre chargé."));
    } else {
      card.tracks.replaceChildren(
        ...pool.map((track) => {
          const item = el("li", "track");
          item.appendChild(el("span", "track-title", trackTitle(track)));
          item.appendChild(el("span", "track-artist", trackArtist(track)));
          return item;
        }),
      );
    }
  }
}

function renderState(payload) {
  const mix = payload.mix || [];
  const players = payload.players || {};
  const sourcePools = payload.source_pools || {};
  const hasLoadedSources = PLAYER_IDS.some((playerId) => (sourcePools[playerId] || []).length > 0);
  const sourceIndex = buildSourceIndex(players, sourcePools);

  // Les noms d'abord : les pastilles des doublons et du mix les reprennent.
  renderPlayers(players, sourcePools);
  renderDuplicates(payload.duplicates || []);
  renderMix(mix, sourceIndex, hasLoadedSources);
  return hasLoadedSources;
}

// --- appels ------------------------------------------------------------------

async function callApi(path, method = "GET") {
  let response;
  try {
    response = await fetch(path, { method, headers: { Accept: "application/json" } });
  } catch {
    throw new Error("Le serveur est injoignable. Vérifie ta connexion puis réessaie.");
  }
  if (response.status === 401) {
    // Session expiree ou mot de passe change : retour a la page de connexion.
    window.location.assign("/login");
    throw new Error("Session expirée, redirection vers la connexion…");
  }

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Une page d'erreur HTML (proxy, redemarrage) n'est pas du JSON.
  }
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : null;
    throw new Error(detail || `Le serveur a répondu par une erreur (HTTP ${response.status}). Réessaie dans un instant.`);
  }
  return payload;
}

function setBusy(activeButton) {
  for (const button of actionButtons) {
    button.disabled = activeButton !== null;
  }
  balancedToggle.disabled = activeButton !== null;
  if (!activeButton) return;

  activeButton.setAttribute("aria-busy", "true");
  const label = activeButton.querySelector('[data-role="label"]');
  if (label && activeButton.dataset.busyLabel) {
    activeButton.dataset.idleLabel = label.textContent;
    label.textContent = activeButton.dataset.busyLabel;
  }
}

function clearBusy(activeButton) {
  if (activeButton) {
    activeButton.removeAttribute("aria-busy");
    const label = activeButton.querySelector('[data-role="label"]');
    if (label && activeButton.dataset.idleLabel) label.textContent = activeButton.dataset.idleLabel;
  }
  setBusy(null);
}

async function runAction({ button, path, pending, success }) {
  setBusy(button);
  setBadge("busy", "Synchronisation…");
  showNotice("info", pending);
  try {
    const payload = await callApi(path, "POST");
    renderState(payload);
    setBadge("ok", "À jour");
    showNotice("success", typeof success === "function" ? success(payload) : success);
    return true;
  } catch (error) {
    setBadge("error", "Erreur");
    showNotice("error", error.message);
    return false;
  } finally {
    clearBusy(button);
  }
}

async function loadStatus() {
  setBadge("busy", "Chargement…");
  try {
    const payload = await callApi("/api/status");
    const hasLoadedSources = renderState(payload);
    if (hasLoadedSources) {
      setBadge("ok", "À jour");
      hideNotice();
    } else {
      setBadge("idle", "À charger");
      showNotice("info", "Aucune playlist chargée : ouvre « Avancé » pour le premier chargement depuis Deezer.");
    }
  } catch (error) {
    setBadge("error", "Erreur");
    showNotice("error", error.message);
  }
}

function withBalanced(path) {
  return `${path}?balanced=${balancedToggle.checked}`;
}

// --- actions -----------------------------------------------------------------

generateButton.addEventListener("click", () => {
  runAction({
    button: generateButton,
    path: withBalanced("/api/generate"),
    pending: "Génération du mix et publication sur Deezer…",
    success: balancedToggle.checked
      ? "Nouveau mix publié sur Deezer, en mode équitable."
      : "Nouveau mix publié sur Deezer.",
  });
});

for (const playerId of PLAYER_IDS) {
  const button = cards[playerId].button;
  button.addEventListener("click", () => {
    const name = playerNames[playerId];
    runAction({
      button,
      path: withBalanced(`/api/refresh/${playerId}`),
      pending: `Rechargement de ${name} depuis Deezer…`,
      success: (payload) => `${payload.players?.[playerId]?.name || name} rechargée, mix republié.`,
    });
  });
}

function closeResetConfirm() {
  resetConfirm.hidden = true;
  resetButton.hidden = false;
}

resetButton.addEventListener("click", () => {
  resetButton.hidden = true;
  resetConfirm.hidden = false;
  // L'action est lourde : le focus va sur l'option sans consequence.
  resetCancelButton.focus();
});

resetCancelButton.addEventListener("click", () => {
  closeResetConfirm();
  resetButton.focus();
});

resetConfirm.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeResetConfirm();
    resetButton.focus();
  }
});

resetConfirmButton.addEventListener("click", async () => {
  await runAction({
    button: resetConfirmButton,
    path: "/api/reset",
    pending: "Rechargement des trois playlists depuis Deezer…",
    success: (payload) => {
      const names = PLAYER_IDS.map((playerId) => payload.players?.[playerId]?.name).filter(Boolean);
      return names.length > 0
        ? `Playlists rechargées (${names.join(", ")}), mix republié.`
        : "Réinitialisation terminée, mix republié.";
    },
  });
  closeResetConfirm();
});

// Preference d'affichage seulement : le serveur ne retient pas ce mode.
try {
  balancedToggle.checked = window.localStorage.getItem(BALANCED_STORAGE_KEY) === "true";
} catch {
  // Stockage indisponible (navigation privee) : interrupteur desactive par defaut.
}
balancedToggle.addEventListener("change", () => {
  try {
    window.localStorage.setItem(BALANCED_STORAGE_KEY, String(balancedToggle.checked));
  } catch {
    // Sans stockage, le choix vaut pour la session en cours.
  }
});

loadStatus();
