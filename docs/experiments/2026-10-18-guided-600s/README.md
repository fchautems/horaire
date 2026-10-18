# Recherche guidée — 18 octobre 2026

**Recherche achevée normalement après 600,518 secondes, sans solution trouvée.** Statut CP-SAT : **UNKNOWN**, aucune solution ni checkpoint. Ce résultat ne démontre ni l'infaisabilité du problème ni un bug.

- Début : 22:25:04 CEST ; sortie normale à 22:35:05 CEST (code 0, suivi compris).
- Autorisation : Frédéric demande le lancement après explication du calcul guidé.
- Point de départ : candidat historique dans `docs/experiments/2026-10-17-global-restart-300s/evidence.json`, entrée `result.json`.
- Ce planning est fourni comme hint, jamais comme contrainte : aucun horaire ni affectation fixé ; les groupes principaux restent libres sous les règles métier.
- Même moteur compact CP-SAT et mêmes options que l'essai précédent depuis zéro. Les contraintes de déplacement restent actives : dix minutes entre sites, zéro entre groupes du même site.
- Modèle : 23 491 variables, 64 198 contraintes. Recherche automatique unique pendant 599,703 s ; 3 891 conflits, 394 253 branches, zéro solution.
- Référence historique conservée : invalide à cause de sept déplacements sans délai. Aucun planning actif remplacé, aucun nouveau candidat sélectionné.
- Contrôles : code de sortie 0 et empreintes des sources, données et configuration inchangées. Aucun nouveau test de production exécuté pour cet essai sans modification de production ; le dernier contrôle publié reste à 103 tests réussis.
- Aucun autre calcul lancé après cet essai. Prochaine piste : diagnostiquer les contraintes autour des remplacements et des déplacements pour déterminer ce qui bloque la recherche. Aucun assouplissement des règles décidé.

`summary.json` contient le résumé structuré ; `evidence.json` conserve les scripts, les conditions, les journaux, le résultat brut, la revalidation de l'historique et les contrôles.
