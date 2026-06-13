# Codex : commencer ici

Lire dans cet ordre :

1. `CURRENT_TASK.md` : unique prochaine tache.
2. `CURRENT_STATE.md` : etat reel du projet et fichiers importants.
3. `DECISIONS.md` : regles metier et choix techniques a ne pas casser.
4. `BUGS.md` : problemes connus et statut.

Reference metier detaillee : `docs/REGLES_METIER.md`.
Documentation utilisateur : `docs/DOCUMENTATION_UTILISATEUR.md`.

Regles de reprise :

- ne pas modifier `data/gwendo.json` pour faire artificiellement passer le solveur ;
- ne pas assouplir une contrainte hard sans validation explicite du metier ;
- ne pas considerer un timeout comme une preuve d'infaisabilite ;
- verifier les changements locaux avec `git status` avant toute modification.

Etat Git de reference : branche `main`, commit `092407e`.
