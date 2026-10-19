# Diagnostic des déplacements — 19 octobre 2026

## Résultat démontré

Le remplacement historique de **Fanny le lundi** ne peut pas être conservé avec ses activités avant et après, deux trajets avec délai et un maximum de deux périodes de présence. Les deux interruptions nécessaires produisent **trois périodes**. C'est un conflit local entre cette organisation et les contraintes du modèle ; aucun nouveau bug ni impossibilité du planning global n'est démontré.

Le code traite les trajets comme du temps sans présence : ils séparent donc les périodes, comme une autre interruption. La question de savoir si un déplacement devrait au contraire faire partie d'une période de travail n'a pas été tranchée ici. Aucun changement de définition métier n'est fait.

## Comparaisons causales

Six cas isolés exécutés, dont cinq appels CP-SAT à budget maximal de trois secondes chacun. Le sixième cas est refusé avant résolution car le moteur compact ne supporte pas trois périodes. Exécution complète finale : moins d'une seconde.

| Cas isolé | Périodes | Validateur | CP-SAT |
|---|---:|---|---|
| Historique : haut → bas → haut sans délai | 1 | Deux déplacements insuffisants | INFEASIBLE |
| Témoin : mêmes horaires sur un même site | 1 | Valide | OPTIMAL, valide |
| Deux trajets avec un créneau libre à chaque passage | 3 | Maximum de deux dépassé, seule erreur | INFEASIBLE |
| Même cas avec maximum de trois, diagnostic uniquement | 3 | Valide | Option refusée explicitement |
| Un trajet, activité avant puis remplacement | 2 | Valide | OPTIMAL, valide |
| Un trajet, remplacement puis activité après | 2 | Valide | OPTIMAL, valide |

Le cas avec trajets utilise **11:45–13:00 Grands (haut)**, **13:15–14:00 remplacement Trotteur (bas)** et **14:15–18:15 Grands (haut)**. La grille de quinze minutes réserve un créneau vide pour chacun des deux trajets de dix minutes minimum.

Contrôle indépendant : énumération de **126 755** intervalles seuls ou paires d'intervalles possibles sur les 48 créneaux de la journée, en imposant ces trois activités et les deux créneaux de trajet libres. **Aucune couverture en au plus deux périodes**. Les cas à un seul trajet montrent que les contraintes de déplacement et de périodes ne sont pas toujours incompatibles.

## Contrôle de la semaine réelle

Le candidat historique a exactement sept erreurs, toutes liées aux déplacements. Un essai documentaire conserve les remplacements et insère un créneau libre avant/après chaque passage entre sites, en réduisant les activités ordinaires adjacentes. Une activité de quinze minutes devenue vide est retirée. Aucun autre ajustement n'est fait.

| Personne et jour | Trajets | Périodes avant | Périodes après |
|---|---:|---:|---:|
| A repourvoir, mardi | 2 | 1 | 3 |
| Fanny, lundi | 2 | 1 | 3 |
| Priscila, mardi | 2 | 2 | 3 |
| Valérie, jeudi | 1 | 1 | 2 |

Les sept erreurs de déplacement disparaissent, mais ce candidat reste invalide : **trois journées dépassent deux périodes** et **cinq créneaux manquent d'une personne** :

| Jour | Groupe | Créneau | Effectif / minimum |
|---|---|---|---|
| Lundi | Grands | 13:00–13:15 | 1 / 2 |
| Mardi | Nurserie | 14:00–14:15 | 1 / 2 |
| Mardi | Trotteur | 13:00–13:15 | 1 / 2 |
| Mardi | Trotteur | 14:15–14:30 | 1 / 2 |
| Jeudi | Grands | 13:00–13:15 | 1 / 2 |

## Portée et suite précise

Les petits cas gardent les groupes, sites, heure du colloque Trotteur et activités historiques de Fanny. Ils isolent une seule personne et fixent Grands comme groupe principal ; le contrat est ajusté aux heures du cas, le THE est désactivé, les demandes de couverture et pourcentages sont retirés. Ces simplifications servent à isoler la cause ; ce ne sont pas des propositions pour la semaine réelle.

La semaine modifiée est, elle, contrôlée avec les données réelles et les mêmes options que les essais de 600 secondes, sans retirer de règle. Aucun nouveau calcul global n'a été lancé.

La prochaine hypothèse à tester est une réorganisation des remplacements et des journées autour des cinq créneaux identifiés, en respectant dix minutes de déplacement et deux périodes. Conserver les mêmes trois activités pour une personne qui doit effectuer un aller-retour est désormais une voie exclue sous ces règles. Aucune augmentation du nombre de périodes ni redéfinition des trajets n'est décidée.

La raison complète des deux recherches globales UNKNOWN reste inconnue. Ce diagnostic explique pourquoi une simple insertion de délais dans l'historique échoue ; il ne prouve pas pourquoi toute la recherche n'aboutit pas.

## Reproduction et traces

- OR-Tools 9.15.6755, environnement isolé ; Python 3.12.
- Commande : `python docs/experiments/2026-10-19-travel-diagnostic/run.py` avec OR-Tools installé.
- `evidence.json` conserve le script, les six cas, l'énumération, la revalidation hebdomadaire et le journal final. `summary.json` résume les contrôles.
- Empreintes du code de production, des données et de la configuration identiques à l'essai guidé du 18 octobre. Aucun planning actif remplacé, aucun fichier de production modifié. Aucun nouvel audit exhaustif ni suite complète de tests revendiqués.
