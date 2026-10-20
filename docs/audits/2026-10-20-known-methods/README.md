# Choix d’une méthode établie pour la génération initiale

Date : 20 octobre 2026. Base examinée : `23da73d9064f2327f37ea23d637e89bdd5c7ed8e`.

## Conclusion et périmètre

**Méthode recommandée pour un premier prototype : phase de faisabilité élastique L1 sur la couverture, puis optimisation de la qualité sous toutes les règles hard.** Référence concrète : exemple officiel de planification du personnel `workforce4` de Gurobi [1], complété par sa documentation de relaxation de faisabilité [2]. Le principe mathématique est transposable à CP-SAT ; cette recommandation n’implique ni installation de Gurobi, ni licence, ni migration du projet.

La revue demandée consiste à inventorier les mécanismes actuels et à choisir une technique publiée. Elle ne modifie ni le solveur ni les règles. La sélection du premier sous-ensemble à rendre élastique est une recommandation pour ce projet, pas un résultat de performance démontré ni une décision d’assouplissement des règles finales.

La recherche à grand voisinage (LNS) est une autre méthode établie pour les plannings de personnel [3]. Une boucle LNS métier sera envisagée après la construction initiale si les mesures le justifient ; elle ne constitue pas à elle seule une solution au démarrage sans candidat. Les techniques internes de CP-SAT ne sont pas réimplémentées dans cette revue.

## Ce qui existe déjà, vérifié dans le code

| Mécanisme | État observé | Point d’entrée et limite |
| --- | --- | --- |
| Première solution puis amélioration | Déjà présent | `solver.make_ortools_slot_payload` arrête la recherche initiale à la première solution, la valide puis optimise avec le temps restant. L’objectif de qualité existe déjà pendant cette recherche : il n’est pas nécessaire d’inventer deux phases qui existent. |
| Plusieurs stratégies de recherche | Déjà présent | Hypothèses de groupes puis stratégies `automatic`, `portfolio`, `pseudo_cost` avec graines fixes. Cela ne construit pas une population de plannings approximatifs. Dans l’essai de 600 s, le budget a été consommé avant la troisième stratégie générale. |
| Indice de planning complet ou partiel | Déjà présent | `hint_payload` est traduit en valeurs indicatives ; aucun engagement à les respecter. OR-Tools documente aussi les indices invalides [4]. Un hint n’est pas une mesure des violations ni une garantie de réparation. |
| Élargissement du domaine des patrons | Déjà présent | `pattern_search.build_candidate_attempts` passe de patrons simples/coarse à un domaine plus large. Il élargit les décisions permises, sans rendre automatiquement les contraintes métier élastiques. |
| Faisabilité puis amélioration par patrons | Déjà présent | Branche `pattern_mip` de `solver.main`. `feasible_only` conserve les coûts soft dans HiGHS ; il ne supprime pas les lignes hard. |
| Diagnostic avec jours assouplis | Déjà présent, limité | L’orchestrateur peut désactiver `hard_max_work_days` puis marque le résultat `invalid`/`diagnostic_only`. Il n’enchaîne pas sur une restauration stricte de cette règle. |
| Interrupteurs de diagnostic du compact | Déjà présents, non orchestrés en réparation | `enforce_percentage_rules`, `enforce_daily_hours`, `enforce_weekly_hours`, etc. désactivent des familles. `accept_invalid_for_hint` permet de rendre un candidat invalide, mais ne crée pas un objectif de violations. Aucun appel de production inspecté n’active ce dernier paramètre. |
| Phase élastique avec violations chiffrées | Absente des chemins inspectés | La couverture reste directement imposée par des inégalités hard ; pas de variables de déficit ni d’objectif de réparation de ces déficits. |
| LNS métier explicite | Absente des chemins inspectés | Pas de boucle libérant puis réparant des fragments du planning. Le compact `fixed_schedule` fixe toute la semaine ; les patrons disposent de fixations partielles par journée, utilisables pour une future boucle. CP-SAT possède par ailleurs ses propres sous-solveurs LNS/LS [5] : cette absence concerne la couche applicative. |

Le constat « première solution difficile » porte sur le compact. Le dernier essai depuis zéro n’a pas exécuté l’orchestrateur `pattern_mip` complet ni l’interface Windows. Il ne mesure donc pas toutes les voies du programme.

## Observations exécutées

`probes.py` caractérise les API existantes sur une personne, un contrat de deux heures et une fenêtre de deux heures le lundi. Aucun besoin de couverture, qualification, THE ou colloque : ces témoins n’évaluent pas la performance réelle.

| Cas | Résultat observé |
| --- | --- |
| Semaine fixée à 08:00–10:00 lundi | `ok`, aucune erreur, CP-SAT `OPTIMAL`. |
| `fixed_schedule` ne contenant que 08:00–09:00 | `INFEASIBLE` : les créneaux non fournis sont fixés à zéro, ils ne sont pas laissés libres pour compléter le contrat. |
| Même fixation, heures hebdomadaires désactivées et `accept_invalid_for_hint=True` | Une heure rendue, statut `invalid`, écart contractuel conservé, aucun checkpoint valide. Aucune réparation automatique n’est déclenchée. |
| Candidat invalide précédent fourni comme hint au modèle strict, sans fixation | Deux heures trouvées, `ok`, aucune erreur. Cette capacité sur un cas facile ne démontre pas une réparation efficace de la semaine réelle. |

Les quatre résolutions ont terminé en moins d’une seconde cumulée ; valeurs détaillées et assertions dans `results.json` et `probes.log`. Douze tests existants ciblés réussis : quatre sur l’orchestration et huit sur les essais par patrons. Ce sont des vérifications ciblées ; la suite complète n’a pas été relancée pour cette modification exclusivement documentaire et ces sondes.

Les empreintes des sources de production, des données, de la configuration et des sorties sont identiques avant/après les sondes. Aucun nouveau calcul global lancé. Aucun optimum ou gain de performance global revendiqué.

## Pourquoi retenir une phase de faisabilité élastique d’abord

Dans `workforce4`, les besoins de personnel reçoivent des variables artificielles d’écart ; une première résolution minimise leur somme, puis une seconde améliore un autre critère en conservant le niveau d’écart atteint [1]. La documentation générale permet de choisir explicitement les contraintes relâchées et la mesure du coût, dont la somme des violations (L1) [2].

Le projet peut reprendre ce schéma avec une exigence finale plus stricte : **seul un écart nul et une revalidation hard complète permettent de proposer le planning**. Un minimum positif resterait un diagnostic, même si un exemple de bibliothèque l’autorise dans sa seconde phase.

Pour un premier prototype isolé, le choix proposé est de rendre uniquement les minimums de couverture élastiques. Les contraintes de présence, contrats/THE, qualifications, déplacements, colloques, groupes, nombre de jours/périodes, plafonds et coupures de 90 minutes restent strictes. Ce choix vise un écart homogène et explicable, sans désactiver plusieurs familles simultanément. Il ne garantit pas que le modèle restant soit facile ou faisable.

Pour chaque exigence de couverture d’un groupe/site et créneau, introduire un entier non négatif `deficit` et remplacer uniquement la borne minimum par `presence + deficit >= besoin`. La borne supérieure éventuelle reste inchangée. Borner le déficit par le besoin, puis minimiser sa somme, sans mélanger les préférences à cet objectif de première phase. Les exigences groupe et site doivent rester identifiables : une somme de déficits de lignes qui se recouvrent n’est pas un total d’heures humaines manquantes distinctes.

Une solution à déficit nul est une solution candidate du modèle strict ; la vérifier puis poursuivre l’objectif de qualité existant en fixant tous les déficits à zéro. Il n’est pas nécessaire de prouver l’optimalité d’un objectif non négatif lorsque zéro est atteint. Un écart positif sous timeout ne prouve rien sur l’infaisabilité stricte. Une éventuelle preuve doit concerner le modèle élastique complet et fidèle, sans restriction provisoire de groupes ou de voisinage.

Cette phase privilégie le degré d’infaisabilité et sépare strictement faisabilité et qualité, principes documentés par Timefold [6]. Le schéma de deux phases est également étudié en nurse rostering [7]. La liste des contraintes temporairement élastiques et leurs unités doit être déclarée dans chaque essai ; aucun indicateur global « invalide » ne remplace le détail des déficits.

## Autres techniques : place et limites

- **LNS / fix-and-optimize** : justifiée pour recalculer des fragments autour d’un candidat ; documentée pour le personnel [3]. Le choix des fragments est important. La fixation totale du compact n’est pas une API de voisinage partiel. Une extension de cette API serait nécessaire pour une boucle métier avec ce moteur.
- **Construction gloutonne, plusieurs départs** : techniques possibles, mais elles demanderaient ici de coder une construction spécifique et de caractériser sa réparabilité. Non retenues comme premier changement, faute de preuve que cette couche soit nécessaire.
- **Simple suppression de contraintes puis hint strict** : possible avec les interrupteurs présents ; sans objectif chiffré des violations, elle peut rendre un candidat très éloigné de la faisabilité. Le microcas établit la mécanique, pas son efficacité réelle.
- **Réglage du moteur ou délai accru** : à comparer comme témoins, sans prétendre qu’un autre paramètre ou davantage de temps résoudrait le problème.

## Protocole proposé pour l’étape d’implémentation

1. Isoler la construction du modèle et son contrôle strict pour éviter deux définitions des règles. Ajouter une option expérimentale de couverture élastique, désactivée par défaut, avec statut de diagnostic et déficits détaillés.
2. Vérifier par microcas la réduction mesurée du déficit, l’absence de compromis avec le confort, le passage à zéro puis le rejet d’un déficit positif. Vérifier les protections de contrats, qualifications, voyages et coupures ; ne jamais réutiliser un validateur assoupli pour la sortie finale.
3. Avant tout benchmark long, revalider le candidat réel connu puis le fixer dans le modèle expérimental : les déficits doivent être zéro, sans changer ses affectations. Rejouer les tests nécessaires après modification du moteur.
4. Comparer le compact actuel et ce prototype sur les mêmes données, matériel, règles, budget global et options de qualité, **sans horaire fourni**. Exposer et enregistrer la graine pour les deux variantes. Prévoir plusieurs exécutions, en limitant d’abord la campagne ; aucune campagne n’est lancée par cette revue.
5. Mesurer : taux de solutions hard-valides, temps jusqu’au premier zéro/revalidation, meilleure violation restante par famille en cas d’échec, qualité au même temps total, temps de construction et mémoire. Séparer résultats et échecs de processus ; conserver les journaux et empreintes.

La revue choisit une première technique à évaluer. L’adoption en production dépendra de ces résultats ; aucun réglage plus performant n’est encore démontré.

## Références primaires consultées

1. Gurobi, [workforce4.py, exemple officiel de planning du personnel](https://docs.gurobi.com/projects/examples/en/current/examples/python/workforce4.html) : variables de slack, premier objectif de faisabilité, puis second objectif.
2. Gurobi, [Infeasibility Analysis — Relaxing for Feasibility](https://docs.gurobi.com/projects/optimizer/en/current/features/infeasibility.html) : choix des contraintes, variables artificielles, coût L1/L2/L0. Référence méthodologique, aucune dépendance ajoutée.
3. Fang He et Rong Qu, [A Constraint-directed Local Search Approach to Nurse Rostering Problems](https://arxiv.org/abs/0910.1253), EPTCS 5, 2009 : LNS guidée par contraintes, sélection des fragments.
4. Google OR-Tools, [CP-SAT model documentation — Solution hinting](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/model.md) : indice partiel/invalide possible, sans contrainte de fixation.
5. Google OR-Tools, [sat_parameters.proto](https://github.com/google/or-tools/blob/stable/ortools/sat/sat_parameters.proto) : mécanismes de sous-solveurs et paramètres LNS/LS. Les valeurs de la branche stable consultée ne remplacent pas celles de la version installée 9.15.6755.
6. Timefold, [Constraints and score](https://docs.timefold.ai/timefold-solver/latest/constraints-and-score/overview) et [Performance tips — score traps](https://docs.timefold.ai/timefold-solver/1.x/constraints-and-score/performance) : priorité des niveaux hard/soft et mesure du degré d’infaisabilité.
7. Say Leng Goh et al., [A 2-Stage Approach for the Nurse Rostering Problem](https://www.graham-kendall.com/papers/ssak2022a.pdf), IEEE Access, 2022, DOI 10.1109/ACCESS.2022.3186097 : construction faisable puis amélioration. Les algorithmes MCTS/ILS propres à cet article ne sont pas proposés comme traduction automatique dans le projet.
