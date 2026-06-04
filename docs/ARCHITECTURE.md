# Architecture technique

Le projet est en cours de remise au propre. Le but est d'isoler les responsabilites pour garder le solveur comprehensible et pouvoir faire evoluer les regles metier sans rendre le calcul fragile.

## Modules actuels

### `src/creche_planning/solver.py`

Moteur de calcul et orchestration principale.

Il contient encore plusieurs moteurs historiques (`scipy`, `ortools`, `pattern_mip`). Le moteur utilise par defaut est `pattern_mip`.

### `src/creche_planning/domain.py`

Objets et fonctions de domaine partages :

- jours de la semaine;
- horizon horaire;
- conversion des heures;
- lecture/ecriture JSON;
- demandes de couverture;
- colloques;
- calcul du THE;
- tolerance hebdomadaire;
- plafond hebdomadaire absolu;
- dataclasses utilisees par le solveur.

### `src/creche_planning/reports.py`

Sorties et presentation :

- resume des regles metier;
- export CSV;
- export HTML visuel;
- rapport console.

### `src/creche_planning/runtime.py`

Utilitaires de lancement :

- lecture de `config/solveur_config.json`;
- resolution des chemins;
- horodatage des fichiers;
- aliases de types;
- messages de progression.

### `src/creche_planning/editor.py`

Interface graphique d'edition de `data/gwendo.json` et lancement du solveur.

Les fichiers `creche_editor.py`, `creche_solver.py` et `solveur_v2.py` a la racine sont des lanceurs de compatibilite.

## Prochain decoupage conseille

1. Extraire le moteur `pattern_mip` dans `creche_pattern_solver.py`.
2. Extraire les controles finaux dans `creche_checks.py`.
3. Supprimer ou isoler les anciens moteurs si on decide de ne plus les maintenir.
4. Garder le THE dans le moteur principal `pattern_mip` :
   - contrat total = temps enfants + THE;
   - colloques inclus dans THE;
   - THE hors colloque invisible dans le planning;
   - couverture enfants calculee sans le THE.
5. Garder la notion de groupe principal dans `pattern_mip` :
   - groupe principal impose ou guide par `rules_group`;
   - colloque obligatoire du groupe principal;
   - remplacements de colloque separes de la participation au colloque.

## Regle de prudence

Chaque extraction doit garder le meme comportement et etre suivie par :

```powershell
python -B -m py_compile src/creche_planning/domain.py src/creche_planning/reports.py src/creche_planning/runtime.py src/creche_planning/solver.py src/creche_planning/editor.py
python -B solveur_v2.py --config config/solveur_config.json --output outputs/test.json --csv outputs/test.csv --html outputs/test.html --no-timestamp-outputs
```
