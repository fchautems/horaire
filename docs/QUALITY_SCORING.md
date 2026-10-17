# Score commun du moteur compact et de la sélection

Mise à jour : 17 octobre 2026.

Le chemin compact CP-SAT et la sélection finale utilisent les coefficients de
`compact_quality_context` dans `src/creche_planning/scoring.py`. Le score final
est recalculé à partir des créneaux du planning, pas du champ `objective` enregistré.
Une note plus basse est meilleure. Les contraintes hard et la validation restent
prioritaires : un candidat invalide ne devient jamais acceptable grâce à sa note.

## Critères conservés du moteur compact

| Quantité | Coefficient entier par défaut |
| --- | ---: |
| Créneaux enfants, remplacements inclus | 1 |
| Débuts de périodes de présence continues, première période comprise | 12000 |
| Jours travaillés | 0 dans l'appel direct ; configuration `compact_work_day_weight × 100` dans le lanceur |
| Jours avec plusieurs groupes ordinaires | 800 |
| Couples jour/groupe ordinaire hors groupe principal | 40 |
| Jours hors groupe principal | 3200 |
| Écart absolu au nombre cible de créneaux enfants | 2500 |
| Groupe principal correspondant à la première préférence positive soft | −500 |
| Créneaux travaillés dans une plage négative soft | 45 |
| Créneaux travaillés dans une plage positive soft | −35 |
| Créneaux enfants contraires à une préférence de groupe soft | 18 |

Les poids configurables sont convertis en entiers par le même arrondi dans les
deux calculs. Les règles soft multiples s'additionnent comme dans le moteur
compact existant. Les colloques comptent dans la présence mais pas dans les
créneaux enfants. Les remplacements sont exclus des groupes ordinaires.
Les activités adjacentes n'ajoutent pas de période de présence.

## Cache et compatibilité

Les nouveaux résultats contiennent un champ additionnel `quality_scoring` avec
les seules entrées du calcul (horizon, cibles, règles soft et poids). Un cache
revalidé reconstruit ces entrées à partir des données courantes. Le lanceur
compare tous les candidats avec le contexte de la configuration courante,
y compris les résultats issus d'autres moteurs. Les scores historiques ne sont
pas directement comparables aux nouveaux scores.

L'appel de bas niveau `planning_quality_score` sur un ancien JSON brut sans
contexte conserve son ancien comportement pour compatibilité. Revalider ce JSON
ou fournir explicitement le contexte courant avant de le comparer à un résultat
nouveau. Le lanceur applique déjà cette règle.

## Périmètre

Cet alignement conserve l'objectif existant du moteur compact. Il ne constitue
pas une refonte des priorités métier ni un audit des objectifs des moteurs de
repli/historiques. En particulier, le moteur compact ne pénalise toujours pas
séparément la durée des coupures : son paramètre `split_gap_weight` était et
reste inutilisé. Aucun poids ni contrainte métier n'a été ajouté pour ce sujet.

L'écart aux heures cibles est désormais représenté par une valeur absolue exacte,
également pour la première solution de faisabilité. Cette modification porte sur
une variable auxiliaire et ne réduit pas l'ensemble des horaires autorisés.
