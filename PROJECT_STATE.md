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

## Analyse de reprise — 2026-10-17

### État vérifié
- Copie de lecture récupérée depuis `main`, commit `8d54f70a7e4ef1ec94c55d7e4307631dcb38aa2b` (ajout documentaire du présent fichier). Dernier changement de code : `ea57783`, 2026-06-14.
- Environ 12 448 lignes Python dans `src/creche_planning/`, dont 6 606 dans `solver.py` : les quelque 6 000 lignes correspondent au solveur seul.
- La configuration référence déjà `tests/fixtures/planning_gwendo_reference_valid.json` comme solution initiale : une installation neuve peut donc retrouver cette référence malgré l'absence des sorties locales.
- Revalidation réellement exécutée sur cette référence avec les paramètres de validation de la configuration actuelle : `status: ok`, `checks.errors: []`, score `15630`.
- Le code protège la référence revalidée, utilise CP-SAT pour chercher une amélioration, compare les scores et conserve la référence si le résultat final est invalide ou moins bon.
- Le score de comparaison `planning_quality_score` pénalise les sites/groupes multiples et le nombre de blocs. Il ne mesure pas directement tous les critères soft annoncés (durée des coupures, préférences horaires, marge de couverture). Point à examiner avant une évolution de l'optimisation.

### Contrôles
- Python 3.12.14, environnement Linux : `python -B -m unittest discover -s tests -v`.
- 28 tests exécutés : 26 réussis, 2 échecs dans `test_cp_sat_reference.py`.
- Cause vérifiée des deux échecs : `OR-Tools indisponible: No module named 'ortools'`. Le moteur renvoie alors `infeasible_or_not_solved`. Ce résultat ne démontre pas une infaisabilité métier.
- `requirements.txt` ne déclare toujours que NumPy et SciPy ; OR-Tools est absent de cet environnement.
- Les valeurs par défaut de `verify_solution` diffèrent de la configuration (tolérance de 3 % contre 5 %, coupure maximale de 90 minutes contre aucune limite hard). Les utiliser seules produit des erreurs sur la référence ; la revalidation ci-dessus applique bien la configuration du lancement.
- Aucun calcul autonome complet ni lancement réel de l'interface Windows effectué. Le test d'arrêt Windows est simulé par mocks et ne constitue pas une validation sous Windows.

### Changements et blocages
- Aucun code, test, donnée métier ou paramètre modifié. Seul ce compte rendu est ajouté à `PROJECT_STATE.md`.
- Aucun `AGENTS.md` ni `MODEL_GUIDE.md` trouvé dans l'arborescence du dépôt ; aucun accès Brain disponible parmi les outils exposés.
- Validation CP-SAT bloquée ici par l'absence d'OR-Tools ; les 28 tests ne peuvent pas être déclarés réussis.

### Prochaine action
Reconstituer un environnement avec OR-Tools, relancer les 28 tests puis un calcul borné sur une copie isolée. Vérifier la conservation du score 15630 et des contraintes hard avant toute modification du solveur.
