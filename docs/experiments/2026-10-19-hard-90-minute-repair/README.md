# Réparation sous limite hard de 90 minutes — 19 octobre 2026

## But et règle appliquée

Frédéric a précisé qu'une coupure de 90 minutes est acceptable, mais qu'une coupure de trois heures ne l'est pas. La configuration et les valeurs par défaut imposent donc `max_pause_between_blocks_minutes=90` avec `enforce_max_pause_between_blocks=true`.

L'interruption minimale de quinze minutes réservée à un déplacement intersites reste exclue du calcul des coupures classiques. Elle ne couvre ni enfants ni colloques et n'ajoute pas d'heures contractuelles.

## Reproduction de l'ancien défaut

Le script `run.py` recharge le candidat précédent et le valide avec le maximum hard de 90 minutes. Le résultat observé contient exactement trois erreurs :

- Tara jeudi : 135 minutes, de 10:45 à 13:00 ;
- Léa jeudi : 180 minutes, de 10:00 à 13:00 ;
- Emilie vendredi : 135 minutes, de 12:00 à 14:15.

Le candidat précédent est donc une preuve historique sous l'ancienne configuration, pas un planning acceptable selon la décision métier actuelle.

## Réparation minimale construite

Cinq journées sont réorganisées sans modifier les données ni le planning actif :

| Journée | Réparation |
| --- | --- |
| Tara jeudi | 08:00–10:45 et 12:15–18:00, coupure 90 min |
| Fanny jeudi | 10:45–18:45 |
| Léa jeudi | 08:45–10:45 et 12:15–18:45, coupure 90 min |
| Céline jeudi | 08:00–09:15 puis 10:45–18:00, avec remplacement Nurserie 13:15–14:00, coupure 90 min |
| Emilie vendredi | 08:30–12:45 et 14:15–18:00, coupure 90 min |

Le détail avant/après est dans `changes.json` et le planning complet dans `candidate.json`.

## Résultats exécutés

- Validateur : `ok`, aucune erreur hard et aucune erreur de déplacement.
- CP-SAT avec planning fixé : `OPTIMAL` en 1,092 s ; mêmes affectations par créneau.
- Moteur par patrons avec planning fixé : `Optimal` en 0,022 s ; mêmes affectations par créneau.
- Score commun : 760979 pour le candidat et les deux reproductions.
- Exports CSV et HTML générés à partir du candidat.
- Suite complète : 134 tests réussis en 31,396 s.
- Les sources, données, configuration et sorties protégées n'ont pas changé pendant l'exécution du diagnostic ; le planning actif n'a pas été remplacé.

## Limites techniques

Ces contrôles prouvent la validité du candidat construit et la cohérence des deux moteurs lorsqu'il est fixé. Ils ne prouvent pas que la recherche libre retrouvera ce candidat ni qu'il est optimal globalement.

Quatre recherches courtes antérieures, limitées à 60 secondes, n'ont pas produit de solution : génération/recherche par patrons limitée dans le temps, CP-SAT guidé `UNKNOWN`, puis deux variantes de patrons restreints sans solution primale avant la limite. Ces résultats sont des limites de recherche, pas des preuves d'infaisabilité ni des bugs supplémentaires.

## Fichiers de preuve

- `summary.json` : synthèse exécutable ;
- `conditions.json` : version, options et empreintes avant exécution ;
- `integrity.json` : contrôle des fichiers protégés ;
- `cp-fixed.json` et `patterns-fixed.json` : sorties des moteurs ;
- `candidate.json`, `candidate.csv`, `candidate.html` : candidat et exports ;
- `evidence.json` : empreintes SHA-256 des preuves ;
- `run.py` : reproduction complète et assertions.

