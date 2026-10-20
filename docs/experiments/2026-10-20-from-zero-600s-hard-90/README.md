# Recherche depuis zéro, coupures limitées à 90 minutes — 20 octobre 2026

## Conditions

- Demande : mettre à l’épreuve la génération depuis zéro.
- Version de départ : `deab5fa3119fcf124b71fa9c4056ea7c2a9b2126`.
- Appel direct du moteur compact CP-SAT, budget total de 600 secondes. Même protocole que l’essai depuis zéro du 19 octobre ; différence métier : coupure maximale de 90 minutes activée. Il ne s’agit pas d’un lancement de l’interface Windows ou de l’orchestrateur configuré `pattern_mip`.
- Aucun planning existant chargé : `hint_payload=None`, `fixed_schedule=None`, aucun fichier de référence fourni. Le moteur conserve ses heuristiques internes de groupes calculées à partir des données ; le `hint=True` interne concerne ces groupes, pas la reprise d’un ancien horaire.
- Contraintes hard conservées : couverture, qualifications hebdomadaires par site, contrats/THE, colloques, changements de groupes, déplacements et maximum de deux périodes ordinaires. Les seules interruptions de trajet minimales restent exemptées des coupures classiques. Options exactes dans `conditions.json`.
- Objectif compact par défaut, sans le renforcement de poids spécifique à la dernière recherche guidée. Aucune modification de production durant cet essai.
- Aucun candidat antérieur utilisé comme secours ; aucune sortie active remplacée.

## Reproduction

Dans un environnement Python disposant des dépendances du projet et d’OR-Tools :

```sh
python docs/experiments/2026-10-20-from-zero-600s-hard-90/run.py
```

Le script enregistre tout premier candidat valide, vérifie le résultat final et exporte le rapport HTML avec les horaires individuels si une solution est trouvée. En l’absence de solution, les exports indiquent explicitement l’absence de planning valide.

## Résultat

- Exécution du **20 octobre 2026, de 07 h 10 min 15 s à 07 h 20 min 15 s**, heure suisse ; durée de calcul **600,216 secondes**.
- Fin normale du processus, code de sortie **0**. Statut global **`UNKNOWN`**, zéro solution, aucun checkpoint ; phase d’optimisation non démarrée.
- Six hypothèses internes de groupes : trois `INFEASIBLE` sous leur hypothèse, trois `UNKNOWN` en 30 secondes chacune. Ces refus partiels ne prouvent pas l’infaisabilité globale.
- Recherche générale automatique : 360,185 s, 768 conflits, 189 273 branches, aucune solution.
- Recherche générale portfolio : 148,444 s, 1 857 conflits, 328 254 branches, aucune solution.
- Aucune erreur de processus ni résultat à revalider. Données, configuration, sources et sorties actives identiques par empreintes avant/après.
- Les exports JSON/CSV/HTML indiquent l’absence de planning, sans présenter l’ancien candidat comme résultat de cet essai.

**Conclusion vérifiée : le moteur compact n’a pas trouvé de planning libre en dix minutes avec les règles actuelles.** Cela ne prouve ni l’infaisabilité ni un nouveau bug. Le candidat obtenu précédemment par recherche guidée n’a pas été utilisé et n’est pas remplacé.

Limite : essai du moteur compact, pas de l’orchestrateur `pattern_mip` ni de l’interface Windows. La dernière suite de 134 tests reste celle exécutée avant l’essai ; aucune source de production n’a changé ni nouveau test fonctionnel été ajouté. Une reprise utile consisterait à diagnostiquer la recherche initiale ou à comparer les moteurs sur un protocole explicite, plutôt qu’à répéter strictement le même essai.

## Preuves

`conditions.json`, `run.py`, `run.log`, `cp_sat.log`, `result.json`, `result.csv`, `result.html`, `summary.json`, `integrity.json`, `process_status.json` et `evidence.json`. Les fichiers de checkpoint et de validation ne sont présents que si un candidat est effectivement trouvé.
