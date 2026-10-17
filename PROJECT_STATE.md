# PROJECT_STATE — calcul d'horaires de crèche

Dernière inspection : 2026-10-17 (GitHub, sans exécution locale).

## État vérifié
- Dépôt : `fchautems/horaire`, branche `main`.
- Dernier commit observé : `ea57783a81cf84caee56953f2f9e89ff3cb7eb87` du 2026-06-14 (« Conserver une solution validée tout en poursuivant l’optimisation »).
- Projet Python : éditeur, solveur, modèles de contraintes, rapports et tests dans `src/creche_planning/` et `tests/`.
- Les documents `CURRENT_STATE.md` et `CURRENT_TASK.md` indiquent qu'une grille hard-valide a été obtenue le 2026-06-13 ; ils rapportent 27 tests réussis et un score de référence de 15630. **Résultats historiques, non revérifiés pendant cette inspection.**
- Le commit du 2026-06-14 conserve un planning revalidé comme secours et poursuit la recherche CP-SAT ; le budget configuré passe de 600 à 100 secondes.
- `tests/fixtures/planning_gwendo_reference_valid.json` est suivi par Git. En revanche, `outputs/` ne contient dans Git que `.gitkeep` : les sorties « latest » décrites dans les notes ne sont pas récupérables depuis ce dépôt.
- `BUGS.md` et `docs/ETAT_REPRISE_SOLVEUR.md` contiennent des constats antérieurs à la résolution rapportée dans `CURRENT_STATE.md`. Ne pas interpréter ces anciens constats comme l'état actuel sans tests.

## Changements de cette inspection
- Création du présent fichier de suivi ; aucun code, donnée métier ni configuration modifiés.

## Contrôles réalisés et limites
- Métadonnées GitHub, arborescence, dernier commit, README, fichiers d'état, tâches, décisions, bugs, dépendances et extraits de code/tests consultés.
- Aucun test ni solveur exécuté ; fonctionnement à la date de l'inspection non confirmé.
- `requirements.txt` liste `numpy` et `scipy` ; il faut vérifier comment les dépendances nécessaires au chemin CP-SAT sont installées avant les tests.
- Aucune donnée locale ou modification non commitée n'a pu être inspectée.

## Contraintes à préserver
- Ne jamais assouplir une contrainte hard sans validation métier.
- Vérifier chaque candidat avec `verify_solution`.
- Ne jamais remplacer une solution hard-valide par une solution invalide ou moins bonne.
- Ne pas modifier `data/gwendo.json` pour faire passer artificiellement le solveur.
- Ne pas assimiler un timeout à une preuve d'infaisabilité.

## Prochaine action
Sur une copie de travail isolée (idéalement Codex Cloud), reconstruire l'environnement Python et exécuter la suite de tests à l'état du commit `ea57783`. Vérifier ensuite la conservation de la meilleure solution et les résultats d'optimisation soft, avant toute modification de l'algorithme.
