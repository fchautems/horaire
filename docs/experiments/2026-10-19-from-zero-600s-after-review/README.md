# Relance depuis zéro après la seconde revue — 19 octobre 2026

## But et périmètre

Relance CP-SAT compacte demandée après la correction des défauts R1–R4 de la seconde revue. Le budget est de 600 secondes. Aucun ancien planning n'est fourni comme indice (`hint_payload=null`) et aucun planning n'est fixé (`fixed_schedule=null`). Les options métier sont identiques à la précédente relance depuis zéro.

Cette expérience ne modifie ni le code de production, ni les données, ni la configuration, ni le planning actif. Un éventuel candidat valide aurait été conservé seulement dans ce dossier.

## Résultat observé

- Exécution du 19 octobre 2026, de 12:11:19 à 12:21:20 UTC.
- Temps mesuré dans le solveur : **600,435 secondes**.
- Fin normale du processus : **code de sortie 0**.
- Résultat CP-SAT : **`UNKNOWN`**.
- Aucun planning et aucun checkpoint produits ; aucune validation indépendante de planning n'était donc possible.
- Le résultat ne prouve ni l'infaisabilité du problème, ni un nouveau bug.

Le modèle corrigé contient 35 711 variables et 82 398 contraintes. Trois hypothèses internes de groupes ont été prouvées infaisables ; trois ont expiré avec `UNKNOWN`. La recherche générale automatique a ensuite expiré après 360,299 s, puis le portfolio après 148,670 s. Aucune de ces recherches n'a trouvé de solution.

## Intégrité et preuves

Les empreintes SHA-256 de toutes les sources Python de production, de `data/gwendo.json`, de `config/solveur_config.json` et des fichiers de `outputs/` sont identiques avant et après l'exécution. La liste des différences est vide.

- `conditions.json` : paramètres exacts, versions, commit et empreintes initiales.
- `run.py` : protocole exécutable, callbacks et revalidation prévue de tout candidat.
- `run.log` et `cp_sat.log` : progression et statistiques du solveur.
- `result.json` et `summary.json` : résultat structuré.
- `integrity.json` : comparaison des empreintes avant/après.
- `process_status.json` : heures de début/fin et code de sortie.
- `evidence.json` : contrôles synthétiques et empreintes des artefacts.

## Limite et prochaine action utile

Le budget de dix minutes mesure seulement l'échec de cette stratégie à trouver une solution dans le temps imparti. Une nouvelle relance identique a peu de valeur. La prochaine action utile est un diagnostic court des cinq créneaux de couverture déjà isolés, ou une recherche guidée par une réorganisation explicitement conforme autour de ces créneaux.
