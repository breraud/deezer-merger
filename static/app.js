const statusMessage = document.querySelector("#status-message");
const mixCount = document.querySelector("#mix-count");
const mixList = document.querySelector("#mix-list");
const playerLists = {
  player1: document.querySelector("#player1-list"),
  player2: document.querySelector("#player2-list"),
  player3: document.querySelector("#player3-list"),
};
const playerCounts = {
  player1: document.querySelector("#player1-count"),
  player2: document.querySelector("#player2-count"),
  player3: document.querySelector("#player3-count"),
};
const buttons = Array.from(document.querySelectorAll("button"));

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

  tracks.forEach((trackId) => {
    const item = document.createElement("li");
    item.textContent = `Track ID ${trackId}`;
    container.appendChild(item);
  });
}

function renderState(payload) {
  const mix = payload.mix || [];
  const players = payload.players || {};
  const sourcePools = payload.source_pools || {};

  mixCount.textContent = `${mix.length} titres`;
  renderTrackList(mixList, mix);

  Object.entries(playerLists).forEach(([playerId, element]) => {
    renderTrackList(element, players[playerId] || []);
  });

  Object.entries(playerCounts).forEach(([playerId, element]) => {
    const totalLoaded = (sourcePools[playerId] || []).length;
    element.textContent = `${totalLoaded} titres charges`;
  });
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
    renderState(payload);
    statusMessage.textContent = "Etat charge depuis le serveur.";
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
    statusMessage.textContent = successMessage;
  } catch (error) {
    statusMessage.textContent = error.message;
  } finally {
    setLoading(false);
  }
}

document.querySelector("#generate-button").addEventListener("click", () => {
  triggerAction("/api/generate", "Generation du mix et mise a jour Deezer...", "Mix global regenere.");
});

document.querySelector("#reset-button").addEventListener("click", () => {
  triggerAction("/api/reset", "Reset complet, rechargement des playlists et synchro Deezer...", "Reset complet termine.");
});

document.querySelectorAll("[data-player]").forEach((button) => {
  button.addEventListener("click", () => {
    const playerId = button.dataset.player;
    const playerLabel = playerId.replace("player", "Joueur ");
    triggerAction(
      `/api/refresh/${playerId}`,
      `Rafraichissement de ${playerLabel} et synchronisation Deezer...`,
      `${playerLabel} rafraichi avec succes.`,
    );
  });
});

refreshStatus();
