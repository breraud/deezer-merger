// Simulation locale : chaque visite repart de ces playlists fictives.
// Aucun appel réseau, aucune écriture dans le cache ou dans Deezer.
window.createDemo = function createDemo() {
  const ids = ["player1", "player2", "player3"];
  const track = (id, title, artist) => ({ id, title, artist });
  const shared = track("demo-shared", "Sous les étoiles", "Les Satellites");
  const pools = {
    player1: [
      shared,
      track("demo-1", "Dernier métro", "Minuit Bleu"),
      track("demo-2", "Néons", "Les Satellites"),
      track("demo-3", "La ville s’éveille", "Écho Libre"),
      track("demo-4", "À contretemps", "Minuit Bleu"),
      track("demo-5", "Horizon", "Écho Libre"),
    ],
    player2: [
      shared,
      track("demo-6", "Au grand air", "Les Passagers"),
      track("demo-7", "Un dimanche", "Camille Rivage"),
      track("demo-8", "Chemin de traverse", "Les Passagers"),
    ],
    player3: [
      track("demo-9", "Pulsations", "Studio Nova"),
      track("demo-10", "Après minuit", "Onde Douce"),
      shared,
      track("demo-11", "Lumière orange", "Studio Nova"),
      track("demo-12", "Première vague", "Onde Douce"),
    ],
  };
  const names = { player1: "Virée nocturne", player2: "Au grand air", player3: "Électro douce" };
  const players = Object.fromEntries(ids.map(id => [id, { name: names[id], selection: [...pools[id]] }]));
  let mix;

  function shuffle(tracks) {
    const result = [...tracks];
    for (let i = result.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  }

  function rebuild() {
    const unique = new Map();
    for (const id of ids) {
      for (const item of players[id].selection) unique.set(item.id, item);
    }
    mix = shuffle([...unique.values()]);
  }

  function generate(balanced) {
    const count = Math.min(...ids.map(id => pools[id].length));
    for (const id of ids) {
      players[id].selection = balanced ? shuffle(pools[id]).slice(0, count) : [...pools[id]];
    }
    rebuild();
  }

  rebuild();
  return {
    async call(path, method = "GET") {
      const url = new URL(path, "https://demo.local");
      const balanced = url.searchParams.get("balanced") === "true";
      if (method === "POST") {
        if (url.pathname === "/api/reset") {
          generate(false);
        } else if (url.pathname === "/api/generate") {
          generate(balanced);
        } else if (url.pathname.startsWith("/api/refresh/")) {
          const id = url.pathname.split("/").pop();
          if (!ids.includes(id)) throw new Error("Playlist de démonstration inconnue.");
          if (balanced) {
            const count = Math.min(...ids.map(id => pools[id].length));
            const selected = new Set(players[id].selection.map(item => item.id));
            const available = pools[id].filter(item => !selected.has(item.id));
            players[id].selection = shuffle(available.length >= count ? available : pools[id]).slice(0, count);
            rebuild();
          } else {
            generate(false);
          }
        } else {
          throw new Error("Action de démonstration inconnue.");
        }
      } else if (method !== "GET" || url.pathname !== "/api/status") {
        throw new Error("Action de démonstration inconnue.");
      }
      return structuredClone({
        source_pools: pools,
        players,
        mix,
        duplicates: [{ ...shared, players: [...ids] }],
      });
    },
  };
};
