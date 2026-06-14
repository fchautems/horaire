# Etat actuel du projet

Date de reference : 13 juin 2026.

## Etat fonctionnel

Le projet genere, verifie et exporte un planning hebdomadaire de creche.
L'editeur, les lanceurs Windows, le cache JSON et les exports JSON/CSV/HTML
restent compatibles.

Le moteur configure reste `pattern_mip`, mais son orchestration utilise
maintenant une recherche compacte CP-SAT avant le modele exhaustif lorsqu'aucun
planning hard-valide n'est disponible.

## Resultat principal

Un planning strictement hard-valide est maintenant confirme :

- fichier actif : `outputs/planning_gwendo_latest.json` ;
- `status: ok` ;
- `checks.errors: []` ;
- score interne de qualite : `15630` ;
- verification finale : `OK`.

Ce planning provient de la grille metier du 2 juin 2026, avec les corrections
minimales deja documentees de couverture et de classification des remplacements
de colloque. La reference immuable est :

`outputs/planning_gwendo_reference_valid_2026-06-13_19-27-08.json`

Les versions CSV et HTML correspondantes existent aussi.

## Corrections du solveur

Le moteur compact CP-SAT a ete aligne sur `verify_solution` :

- heures enfants, THE et colloques comptabilises comme le validateur ;
- limites de jours travaillees appliquees ;
- maximum de deux blocs et coupures controlees ;
- changement de site permis entre deux parties d'une journee ;
- changement de groupe interdit dans une meme demi-journee ;
- remplacements de colloque exclus des changements ordinaires de groupe ;
- groupes principaux et regles hard correctement interpretes ;
- tout candidat est obligatoirement soumis a `verify_solution`.

Le CP-SAT a reproduit exactement le planning de reference en environ 5 secondes
dans le test d'equivalence. Sans planning fixe, il a aussi produit de maniere
autonome un candidat avec `checks.errors == []` : premiere faisabilite en
environ 25 secondes, puis amelioration limitee a 60 secondes.

Le modele exhaustif par patrons reste disponible en repli. Il n'est plus lance
si un planning hard-valide a deja ete trouve ou revalide.

## Cache et securite

- `planning_gwendo_latest.json` est prioritaire sur les JSON de diagnostic ou
  de test plus recents ;
- le cache est revalide avec les donnees et regles courantes avant reutilisation ;
- un cache incomplet ou invalide est refuse ;
- un planning valide n'est jamais remplace par un candidat invalide ;
- les anciens diagnostics CP-SAT ne sont plus affiches comme diagnostics du
  lancement courant.

Le lancement reel avec `config/solveur_config.json` a termine en 0,78 seconde :

- `Dernier planning hard-valide revalide et conserve` ;
- `Verification: OK` ;
- aucun modele exhaustif lance.

## Tests

Commande utilisee :

`F:\anaconda3\envs\stable-diffusion\python.exe -m unittest discover -s tests -v`

Resultat : 27 tests passes en environ 5 secondes.

Les tests couvrent notamment :

- contraintes de groupe et changements entre demi-journees ;
- remplacements de colloque ;
- budgets et replis du moteur par patrons ;
- conservation d'un candidat valide ;
- timeout et arret de l'arbre de processus sous Windows ;
- revalidation et priorite du cache ;
- equivalence du planning de reference dans CP-SAT.

## Fichiers modifies dans le travail courant

- `src/creche_planning/solver.py`
- `tests/test_solver_orchestration.py`
- `tests/test_cp_sat_reference.py`
- `tests/fixtures/planning_gwendo_reference_valid.json`
- `CURRENT_STATE.md`
- `CURRENT_TASK.md`

Les donnees `data/gwendo.json` et les formats existants n'ont pas ete modifies
par cette stabilisation.

## Journaux utiles

- `outputs/cp_sat_debug.log` : diagnostic du dernier calcul CP-SAT dans les sorties ;
- `outputs/cp_sat_candidate_test.json` : candidat autonome de diagnostic, valide
  mais moins bon que la reference active.

Ces fichiers de diagnostic ne peuvent plus prendre automatiquement la priorite
sur `planning_gwendo_latest.json`.
