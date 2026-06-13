# Tache suivante

Obtenir un planning hard-valide ou isoler une contradiction metier precise, sans relancer le modele exhaustif de 1,35 million de patrons.

Procedure :

1. Auditer le moteur compact CP-SAT/historique de `solver.py` sur les regles indispensables : jours maximum, THE, colloques, remplacements, staffing, pourcentages et changements de groupe.
2. Ajouter uniquement les contraintes manquantes necessaires pour qu'il puisse servir de generateur rapide de candidat.
3. Soumettre obligatoirement tout candidat a `verify_solution` et refuser toute sortie dont `checks.errors != []`.
4. Conserver le premier candidat hard-valide, puis reparer ou ameliorer uniquement les personnes et journees concernes.
5. Si aucun candidat compact n'existe, extraire une contradiction precise et lisible avant toute nouvelle recherche longue.
6. Ne pas relancer le modele exhaustif actuel de 1,35 million de patrons sans changement d'algorithme ou decomposition.

Faits a conserver :

- le planning assoupli est une base de reparation, pas une preuve stricte ;
- Valerie peut respecter ses 3 jours ;
- les depassements minimaux observes restent A repourvoir, Natacha et Anais ;
- `Time limit reached` n'est pas une preuve d'impossibilite ;
- seul `Infeasible` vaut pour le sous-modele effectivement execute.
- les deux sous-modeles sans coupure du 13 juin sont `Infeasible` ;
- le modele avec coupures n'a pas trouve de candidat dans son budget, ce qui n'est pas une preuve d'infaisabilite ;
- le dernier planning valide n'a pas ete ecrase.

Termine lorsque le planning courant est hard-valide, exporte et explique, ou lorsqu'une contradiction metier precise est demontree par un modele equivalent aux regles validees.
