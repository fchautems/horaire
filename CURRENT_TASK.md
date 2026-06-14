# Tache suivante

Le blocage principal est leve : un planning hard-valide est disponible,
reproductible et reutilise rapidement.

## Objectif

Ameliorer progressivement la qualite du planning sans perdre la solution valide
ni relancer inutilement le modele exhaustif.

## Etapes

1. Garder `planning_gwendo_latest.json` comme solution de secours revalidee.
2. Utiliser cette solution comme indice initial du CP-SAT.
3. Optimiser uniquement les criteres soft : coupures, temps hors groupe
   principal, remplacements et marge de couverture.
4. Verifier chaque candidat avec `verify_solution`.
5. Remplacer le planning actif uniquement si le candidat est hard-valide et
   meilleur selon une comparaison de qualite explicite.
6. Conserver le moteur exhaustif par patrons comme dernier repli, avec budget
   borne et logs de diagnostic.

## Criteres de fin

- `checks.errors == []` ;
- `planning_gwendo_latest.json` jamais remplace par un planning invalide ;
- qualite egale ou meilleure que le score actuel `15630` ;
- tests Windows et lancement reel toujours valides ;
- cache et formats JSON/CSV/HTML inchanges.

## Faits a conserver

- un timeout ne prouve pas l'infaisabilite ;
- le planning actif est strictement valide avec les regles courantes ;
- le CP-SAT sait trouver un candidat valide sans enumerer 1,35 million de patrons ;
- le candidat CP-SAT autonome actuel est valide mais moins bon que la reference ;
- la priorite reste la fiabilite avant l'optimisation soft.
