# Démo interactive

Depuis `/login`, le lien « Essayer la démo » ouvre `/demo` sans mot de passe.
La démo reprend la même interface avec une pastille « Démo » permanente et
les noms neutres « Playlist 1 », « Playlist 2 » et « Playlist 3 ».
Les titres sont tirés au hasard dans un catalogue local d’exemple à chaque
visite. Un titre commun aux trois playlists crée volontairement un conflit :
il apparaît dans le panneau des doublons et une seule fois dans le mix.

La génération, le mode équitable, le rafraîchissement et la réinitialisation
fonctionnent dans le navigateur. Aucun appel aux API de mix, aucune écriture
dans `state.json` et aucune modification sur Deezer. Recharger la page tire
un nouvel exemple ; la préférence de mode équitable est séparée de celle
de l’application connectée. Un lien permet de revenir à la connexion.

La page est marquée explicitement comme démo par le serveur. Ses scripts et
ses styles ont des URL versionnées par leur contenu pour éviter de réutiliser
un ancien script en cache. La réponse interdit les appels fetch/XHR via
`Content-Security-Policy: connect-src 'none'`. Le serveur refuse également les
requêtes aux API réelles dont le référent est `/demo` ou `/demo/`, même avec
une session valide. La protection de la démo ne repose donc pas seulement
sur le choix du gestionnaire JavaScript.

Vérification :

```sh
uv run python -m unittest discover -s tests
node --test tests/test_demo.cjs
```

Le correctif de cache a aussi été vérifié dans Chromium avec une session de
test connectée et un gestionnaire serveur fictif : tous les boutons restent
locaux. En forçant l’ancien `app.js` (commit `2b1903c`), le navigateur bloque
la lecture et le rafraîchissement réels avant leur envoi.
