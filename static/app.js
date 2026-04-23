const statusMessage = document.querySelector("#status-message");
const mixCount = document.querySelector("#mix-count");
const mixList = document.querySelector("#mix-list");
const balancedToggle = document.querySelector("#balanced-toggle");
const playerLists = {
  player1: document.querySelector("#player1-list"),
  player2: document.querySelector("#player2-list"),
  player3: document.querySelector("#player3-list"),
};
const playerTitles = {
  player1: document.querySelector("#player1-title"),
  player2: document.querySelector("#player2-title"),
  player3: document.querySelector("#player3-title"),
};
const playerCounts = {
  player1: document.querySelector("#player1-count"),
  player2: document.querySelector("#player2-count"),
  player3: document.querySelector("#player3-count"),
};
const refreshButtons = {
  player1: document.querySelector("#refresh-player1-button"),
  player2: document.querySelector("#refresh-player2-button"),
  player3: document.querySelector("#refresh-player3-button"),
};
const buttons = Array.from(document.querySelectorAll("button"));
let currentPlayerNames = {
  player1: "Playlist 1",
  player2: "Playlist 2",
  player3: "Playlist 3",
};

function setLoading(isLoading, message) {
  buttons.forEach((button) => {
    button.disabled = isLoading;
  });
  if (message) {
    statusMessage.textContent = message;
  }
}

function renderTrackList(container, tracks) {
  container.innerHTML = "";

  if (!tracks || tracks.length === 0) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "Aucun morceau pour le moment.";
    container.appendChild(item);
    return;
  }

  tracks.forEach((track) => {
    const item = document.createElement("li");
    const artist = track.artist || "Artiste inconnu";
    const title = track.title || `Titre inconnu (${track.id || "?"})`;
    item.innerHTML = `<strong>${artist}</strong> - ${title}`;
    container.appendChild(item);
  });
}

function renderState(payload) {
  const mix = payload.mix || [];
  const players = payload.players || {};
  const sourcePools = payload.source_pools || {};
  const hasLoadedSources = Object.values(sourcePools).some((tracks) => (tracks || []).length > 0);

  mixCount.textContent = `${mix.length} titres`;
  renderTrackList(mixList, mix);

  Object.entries(playerLists).forEach(([playerId, element]) => {
    const playerData = players[playerId] || {};
    renderTrackList(element, playerData.selection || []);
  });

  Object.entries(playerCounts).forEach(([playerId, element]) => {
    const totalLoaded = (sourcePools[playerId] || []).length;
    element.textContent = `${totalLoaded} titres charges`;
  });

  Object.entries(playerTitles).forEach(([playerId, element]) => {
    const playerData = players[playerId] || {};
    const label = playerData.name || currentPlayerNames[playerId] || `Playlist ${playerId.replace("player", "")}`;
    currentPlayerNames[playerId] = label;
    element.textContent = label;
    refreshButtons[playerId].textContent = `Rafraichir ${label}`;
  });

  if (!hasLoadedSources) {
    statusMessage.textContent = "Aucune playlist chargee. Cliquez sur Reset Complet & Sync Deezer pour faire le premier chargement.";
  }

  return hasLoadedSources;
}

function buildActionUrl(path, includeBalanced = false) {
  const url = new URL(path, window.location.origin);
  if (includeBalanced) {
    url.searchParams.set("balanced", String(balancedToggle.checked));
  }
  return `${url.pathname}${url.search}`;
}

async function callApi(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Erreur inconnue");
  }
  return payload;
}

async function refreshStatus() {
  setLoading(true, "Chargement de l'etat courant...");
  try {
    const payload = await callApi("/api/status");
    const hasLoadedSources = renderState(payload);
    if (hasLoadedSources) {
      statusMessage.textContent = "Etat charge depuis le serveur.";
    }
  } catch (error) {
    statusMessage.textContent = error.message;
  } finally {
    setLoading(false);
  }
}

async function triggerAction(path, pendingMessage, successMessage) {
  setLoading(true, pendingMessage);
  try {
    const payload = await callApi(path, { method: "POST" });
    renderState(payload);
    statusMessage.textContent = typeof successMessage === "function" ? successMessage(payload) : successMessage;
  } catch (error) {
    statusMessage.textContent = error.message;
  } finally {
    setLoading(false);
  }
}

document.querySelector("#generate-button").addEventListener("click", () => {
  triggerAction(
    buildActionUrl("/api/generate", true),
    "Generation du mix et mise a jour Deezer...",
    "Mix global regenere.",
  );
});

document.querySelector("#reset-button").addEventListener("click", () => {
  triggerAction(
    "/api/reset",
    "Reset complet, rechargement des playlists et synchro Deezer...",
    (payload) => {
      const names = Object.values(payload.players || {})
        .map((player) => player.name)
        .filter(Boolean);
      return names.length > 0
        ? `${names.join(", ")} recharges depuis Deezer.`
        : "Reset complet termine.";
    },
  );
});

document.querySelectorAll("[data-player]").forEach((button) => {
  button.addEventListener("click", () => {
    const playerId = button.dataset.player;
    const playerLabel = currentPlayerNames[playerId] || `Playlist ${playerId.replace("player", "")}`;
    triggerAction(
      buildActionUrl(`/api/refresh/${playerId}`, true),
      `Rafraichissement de ${playerLabel} et synchronisation Deezer...`,
      (payload) => {
        const refreshedLabel = payload.players?.[playerId]?.name || playerLabel;
        return `${refreshedLabel} recharge.`;
      },
    );
  });
});

refreshStatus();
