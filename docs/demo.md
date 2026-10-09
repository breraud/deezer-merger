# Démo interactive

Depuis `/login`, le lien « Essayer la démo » ouvre `/demo` sans mot de passe.
La démo reprend la même interface avec trois playlists et des titres fictifs,
dont un titre commun pour illustrer la suppression des doublons.

La génération, le mode équitable, le rafraîchissement et la réinitialisation
fonctionnent dans le navigateur. Aucun appel aux API de mix, aucune écriture
dans `state.json` et aucune modification sur Deezer. Recharger la page restaure
les données fictives ; la préférence de mode équitable est séparée de celle
de l’application connectée. Un lien permet de revenir à la connexion.

Vérification :

```sh
uv run python -m unittest discover -s tests
node --test tests/test_demo.cjs
```
