# Recherche depuis zéro — 18 octobre 2026

Recherche achevée normalement : **600,622 secondes**, statut CP-SAT **UNKNOWN**, aucune solution trouvée. Ce résultat ne démontre pas que le problème est infaisable.

- Début : 12:24:20 UTC ; sortie normale à 12:34:22 UTC (code 0, suivi compris).
- Budget demandé : 600 secondes ; dépassement de sortie du solveur : 0,622 seconde.
- Aucun ancien planning fourni comme hint, aucun planning fixé. Les propositions et hints de groupes générés en interne par le solveur restent actifs ; les hypothèses des six essais de groupes sont libérées avant la recherche générale.
- Modèle : 23 491 variables, 64 198 contraintes ; aucun checkpoint ni candidat sélectionné.
- Recherche : six essais de groupes (~91 s), recherche générale automatique (360,295 s), puis portfolio (149,165 s). Les essais partiels INFEASIBLE ne prouvent pas l'infaisabilité du modèle général.
- Règle : dix minutes libres entre sites, aucun délai entre groupes du même site. Colloques et remplacements inclus. Sur la grille de quinze minutes, un créneau vide est nécessaire.
- Référence historique conservée, mais invalide selon la règle des déplacements : sept trajets sans délai. Elle ne sert pas de repli valide.
- Validation avant lancement : 103 tests réussis en 12,157 s ; sources, données et configuration inchangées pendant le calcul.
- Aucun planning actif remplacé. Prochaine piste : rechercher un premier candidat conforme par réparation de l'historique ou par un diagnostic ciblé des déplacements, avant une nouvelle optimisation longue. Aucun nouvel essai lancé automatiquement.

`summary.json` fournit le résumé structuré ; `evidence.json` contient les scripts, les conditions, les journaux, le résultat brut, le suivi de sortie et les contrôles. Le dossier voisin sans suffixe `-retry` conserve séparément le premier essai interrompu.
