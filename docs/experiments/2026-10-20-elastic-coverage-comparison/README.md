# Comparaison initiale du prototype de couverture élastique

Protocole : trois graines (`1`, `17`, `43`), deux modes (compact strict et couverture élastique), 60 secondes par essai, soit six minutes nominales séquentielles. Aucun planning chargé comme hint ni fixé. Ordre alterné selon la graine, processus distincts, même code, données, règles, objectif de qualité et matériel. Les paramètres exacts et empreintes sont enregistrés au lancement.

Il s’agit d’un premier écran à 60 secondes, pas d’une preuve de supériorité ni d’une reproduction à 600 secondes du calcul précédent. Le moteur par patrons et l’interface Windows ne sont pas évalués ici. Les sources de production et sorties actives sont protégées par empreintes.

Validation préalable : 149 tests réussis en 34,761 s (`tests.log`), dont quinze protections et témoins du prototype. Le planning réel connu fixé conserve ses affectations, son score et un déficit nul. Référence de la méthode et détails : `docs/ELASTIC_COVERAGE.md`.

Reproduction depuis la racine dans un environnement avec les dépendances et OR-Tools :

```sh
python docs/experiments/2026-10-20-elastic-coverage-comparison/run.py
```

## Résultats vérifiés

Version testée : `94a0d81f1c1c17ae46550afd6653b6eac1dc9830`. Début de campagne : 20 octobre 2026 à 10 h 17 min 19 s, heure suisse. Six processus terminés normalement, code de sortie 0, aucune interruption par la limite externe de 80 secondes.

| Méthode | Essais | Plannings valides | Premier candidat, même déficitaire | Déficit final | Qualité finale |
| --- | ---: | ---: | --- | --- | --- |
| Compact strict | 3 × 60 s | 0/3 | Aucun | Inconnu | Inconnue |
| Couverture élastique | 3 × 60 s | 0/3 | Aucun | Inconnu | Inconnue |

Tous les statuts de solveur sont `UNKNOWN`. La phase de qualité n’a démarré dans aucun essai. Le prototype n’a pas trouvé de candidat du modèle élastique ; un déficit inconnu ne signifie pas zéro.

| Graine | Mode | Durée calcul (s) | Pic mémoire processus (Mio) |
| --- | --- | ---: | ---: |

| 1 | strict | 60.243 | 1727.5 |
| 1 | elastic | 60.194 | 1694.6 |
| 17 | elastic | 60.174 | 1622.1 |
| 17 | strict | 60.175 | 1784.3 |
| 43 | strict | 60.175 | 1760.6 |
| 43 | elastic | 60.164 | 1660.2 |

Les pics proviennent de `ru_maxrss` dans des processus Linux distincts. Les durées comprennent la construction du modèle et les callbacks, avec un léger dépassement de la limite native globale dû aux terminaisons/contrôles. Détails CPU, construction, stratégies et statistiques dans chaque `summary.json`.

## Interprétation et décision

**Aucun gain de faisabilité n’est démontré par cette première comparaison. Le prototype reste désactivé par défaut.** Ces résultats ne prouvent pas que l’approche serait inutile sous un budget plus long, ni que le modèle strict ou élastique serait infaisable.

Cette campagne est un premier écran limité à trois graines et 60 secondes, sans inférence statistique de supériorité. La recherche reste multithreadée et peut varier malgré les graines. Le compact strict conserve sa phase d’hypothèses internes de groupes ; l’élastique résout directement son modèle complet sans ces hypothèses, comme le prévoit la méthode. Ce ne sont pas des essais de l’orchestrateur par patrons ou de l’interface Windows, ni une comparaison au précédent calcul de 600 secondes.

Le point observé est précis : même en autorisant les manques de couverture, aucun premier horaire satisfaisant les autres contraintes n’a été construit dans ce budget. Cela oriente une prochaine investigation vers la recherche du noyau resté strict ; cela n’identifie pas encore une contrainte responsable et ne justifie pas d’assouplir les règles finales.

## Intégrité et preuves

Sources, données, configuration, fixture historique et sorties actives identiques par empreintes avant/après les six essais. Aucun planning actif remplacé, aucun ancien planning présenté comme résultat et aucun score inventé en l’absence de candidat. La valeur de configuration du prototype est restée `false`.

- `conditions.json`, `run.py` : protocole, environnement, version, paramètres et graines ;
- `run.log`, `partial-summary.json`, `summary.json` : déroulement et synthèse ;
- sous-dossiers par mode/graine : journaux natifs, résultats JSON/CSV/HTML, progression, statut du processus et synthèse ;
- `integrity.json` : empreintes de contrôle ;
- `tests.log` : 149 tests réussis avant la campagne ;
- `evidence.json` : empreintes des preuves.

Les exports HTML de ces essais indiquent l’absence de planning valide ; ils ne contiennent donc pas d’horaires individuels. Le rapport individuel de la précédente solution guidée reste disponible dans son dossier historique.
