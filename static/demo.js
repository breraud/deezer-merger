// Simulation locale : chaque visite repart de ces playlists fictives.
// Aucun appel réseau, aucune écriture dans le cache ou dans Deezer.
window.createDemo = function createDemo() {
  const ids = ["player1", "player2", "player3"];
  const track = (id, title, artist) => ({ id, title, artist });
  // Catalogue local d’exemple : titres connus, aucune playlist utilisateur.
  const catalog = [
    ["Get Lucky", "Daft Punk"],
    ["Lisztomania", "Phoenix"],
    ["Feel Good Inc.", "Gorillaz"],
    ["Levitating", "Dua Lipa"],
    ["Don't Stop Me Now", "Queen"],
    ["Take On Me", "a-ha"],
    ["Midnight City", "M83"],
    ["Blinding Lights", "The Weeknd"],
    ["Dreams", "Fleetwood Mac"],
    ["Mr. Brightside", "The Killers"],
    ["Instant Crush", "Daft Punk"],
    ["Somebody That I Used to Know", "Gotye"],
    ["Electric Feel", "MGMT"],
    ["1901", "Phoenix"],
    ["Kids", "MGMT"],
    ["Clint Eastwood", "Gorillaz"],
    ["Billie Jean", "Michael Jackson"],
    ["Enjoy the Silence", "Depeche Mode"],
    ["Wake Me Up", "Avicii"],
    ["Rolling in the Deep", "Adele"],
  ].map(([title, artist], index) => track(`demo-${index}`, title, artist));
  const sampled = shuffle(catalog);
  // Conflit volontaire : le meme titre appartient aux trois playlists.
  const shared = sampled[0];
  const pools = {
    player1: [shared, ...sampled.slice(1, 6)],
    player2: [shared, ...sampled.slice(6, 9)],
    player3: [shared, ...sampled.slice(9, 13)],
  };
  const names = { player1: "Playlist 1", player2: "Playlist 2", player3: "Playlist 3" };
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
