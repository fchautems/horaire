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


## Résultats actualisés — 17 octobre 2026

Cette section remplace les conclusions provisoires ci-dessus sur l’environnement et les prochaines actions. Aucun code, test, donnée métier ou configuration n’a été modifié.

### Vérifications terminées
- OR-Tools 9.15.6755 installé dans un environnement Python 3.12 isolé.
- **28 tests sur 28 réussis**, en 1,748 seconde, avec `python -m unittest discover -s tests -v`.
- Les deux tests CP-SAT fixent le planning de référence : ils vérifient sa faisabilité, pas la génération libre.
- Référence revalidée : aucune erreur ; score de comparaison 15630.
- Essai sans indice initial et sans planning fixé, budget 100 secondes : aucune solution trouvée, statut `UNKNOWN`, durée totale 101,016 secondes. **Ce résultat ne prouve pas l’impossibilité de produire un horaire.** L’optimisation n’a pas commencé.
- Aucun lancement réel sous Windows effectué.

### Revue du solveur et du validateur

Le **solveur** fabrique l’horaire ; le **validateur** contrôle le résultat. La revue porte sur le moteur compact CP-SAT (`make_ortools_slot_payload`) et `verify_solution` dans `src/creche_planning/solver.py`, avec les helpers de `domain.py` et les règles de `docs/REGLES_METIER.md`. Les autres moteurs ne sont pas intégralement audités.

Les règles de couverture utilisent le même calcul des besoins. Les contrôles des groupes principaux, des colloques et des changements ordinaires par demi-journée sont présents des deux côtés. Cela ne constitue pas une preuve d’équivalence complète.

**Écarts confirmés par cinq petits exemples exécutés en mémoire :**

| Sujet | Exemple | Validateur | CP-SAT avec cet horaire fixé |
| --- | --- | --- | --- |
| Nombre de périodes | Contrat de 3 h, sans THE : lundi 08–09, 10–11 et 13–14 | Aucune erreur | Refus : au plus deux périodes |
| Chevauchements | Contrat de 3 h, sans THE : 08–10 et 09–10, durées déclarées 2 h + 1 h | Aucune erreur | Refus : présence unique par créneau et seulement 2 h distinctes |
| Durée incohérente | Contrat de 3 h, sans THE : 08–12, mais champ `hours=3` | Aucune erreur | Refus : les horaires représentent 4 h |
| THE et minimum de jours | Contrat de 9 h, THE arrondi à 1 h, sans colloque : lundi 08–16 | Aucune erreur : 8 h enfants + 1 h THE invisible | Refus : le minimum de jours est calculé sur 9 h / 8,5 h, soit deux jours |
| Jours hors groupe principal | Contrat de 10 h sans THE, groupe principal A imposé : lundi et mardi 08–13 en B ; limite d’exception 1 | Aucune erreur | Refus : deux jours hors groupe principal |

Précisions :
- Les microcas n’ont pas de besoin de couverture imposé, afin d’isoler les divergences. Tolérance hebdomadaire nulle, maximum journalier 8,5 h et absence de limite hard de coupure.
- Pour le dernier exemple, la personne participe aux colloques mais aucun colloque n’est défini. Le solveur limite à la fois les jours avec plusieurs groupes et les jours hors groupe principal ; le validateur ne limite que les premiers. **Le sens métier voulu doit être clarifié avant correction.**
- Le validateur additionne le champ `hours` pour les totaux, sans le recouper avec les heures de début et de fin. Il ne détecte pas non plus les chevauchements ni le dépassement des deux périodes de présence.
- Le minimum de jours du solveur compte du THE invisible comme s’il nécessitait de la présence. C’est une restriction supplémentaire reproduite sur un temps partiel ; son impact sur les données Gwendo reste à mesurer.

### Conséquences et limites
- Ces écarts sont reproduits ; **ils ne démontrent pas que le planning actuel est incorrect**.
- Ils ne démontrent pas non plus la cause du délai de recherche. Aucun diagnostic de performance complet n’a été effectué.
- Aucun correctif appliqué. Les sondes n’ont pas été ajoutées aux tests du dépôt.
- L’installation d’OR-Tools reste à déclarer dans les dépendances lors d’une future modification autorisée.

### Prochaine action
Préparer des corrections ciblées des contrôles de cohérence du validateur et du minimum de jours avec THE. Clarifier la règle des jours hors groupe principal avant de la modifier. Ne pas relancer de calcul long sans hypothèse précise.

## Décision métier — 17 octobre 2026

Clarification de Frédéric, consignée dans `docs/REGLES_METIER.md` :
- Une journée entière dans un autre groupe que le groupe principal reste possible, si les autres contraintes le permettent. Elle ne compte pas à elle seule comme une journée avec changement de groupe.
- La limite des journées exceptionnelles porte sur les changements en cours de journée ; une matinée dans un groupe et un après-midi dans un autre est possible.
- Une interdiction de groupe hard doit bloquer les affectations ordinaires dans ce groupe, pas uniquement son choix comme groupe principal. Une préférence négative soft doit pénaliser ces affectations.
- L'articulation avec les remplacements de colloque n'est pas encore précisée : aucune exception supplémentaire n'a été inventée.
- Les autres règles, notamment la présence au colloque du groupe principal, restent applicables.

**État : documentation mise à jour ; code inchangé.** La restriction CP-SAT sur les jours hors groupe principal et le traitement des interdictions de groupe doivent être revus selon cette clarification. Les contrôles manquants du validateur et le calcul du minimum de jours avec THE restent à corriger.

Contrôle : relecture des documents publiés ; aucun nouveau calcul ni test nécessaire pour cette modification documentaire. Prochaine action : poursuivre la revue selon ces règles explicites ; toute correction de code reste hors du périmètre actuel.
