# PROJECT_STATE — calcul d'horaires de crèche

Dernière inspection : 2026-10-17 (GitHub, sans exécution locale).

## État vérifié
- Dépôt : `fchautems/horaire`, branche `main`.
- Dernier commit observé : `ea57783a81cf84caee56953f2f9e89ff3cb7eb87` du 2026-06-14 (« Conserver une solution validée tout en poursuivant l’optimisation »).
- Projet Python : éditeur, solveur, modèles de contraintes, rapports et tests dans `src/creche_planning/` et `tests/`.
- Les documents `CURRENT_STATE.md` et `CURRENT_TASK.md` indiquent qu'une grille hard-valide a été obtenue le 2026-06-13 ; ils rapportent 27 tests réussis et un score de référence de 15630. **Résultats historiques, non revérifiés pendant cette inspection.**
- Le commit du 2026-06-14 conserve un planning revalidé comme secours et poursuit la recherche CP-SAT ; le budget configuré passe de 600 à 100 secondes.
- `tests/fixtures/planning_gwendo_reference_valid.json` est suivi par Git. En revanche, `outputs/` ne contient dans Git que `.gitkeep` : les sorties « latest » décrites dans les notes ne sont pas récupérables depuis ce dépôt.
- `BUGS.md` et `docs/ETAT_REPRISE_SOLVEUR.md` contiennent des constats antérieurs à la résolution rapportée dans `CURRENT_STATE.md`. Ne pas interpréter ces anciens constats comme l'état actuel sans tests.

## Changements de cette inspection
- Création du présent fichier de suivi ; aucun code, donnée métier ni configuration modifiés.

## Contrôles réalisés et limites
- Métadonnées GitHub, arborescence, dernier commit, README, fichiers d'état, tâches, décisions, bugs, dépendances et extraits de code/tests consultés.
- Aucun test ni solveur exécuté ; fonctionnement à la date de l'inspection non confirmé.
- `requirements.txt` liste `numpy` et `scipy` ; il faut vérifier comment les dépendances nécessaires au chemin CP-SAT sont installées avant les tests.
- Aucune donnée locale ou modification non commitée n'a pu être inspectée.

## Contraintes à préserver
- Ne jamais assouplir une contrainte hard sans validation métier.
- Vérifier chaque candidat avec `verify_solution`.
- Ne jamais remplacer une solution hard-valide par une solution invalide ou moins bonne.
- Ne pas modifier `data/gwendo.json` pour faire passer artificiellement le solveur.
- Ne pas assimiler un timeout à une preuve d'infaisabilité.

## Prochaine action
Sur une copie de travail isolée (idéalement Codex Cloud), reconstruire l'environnement Python et exécuter la suite de tests à l'état du commit `ea57783`. Vérifier ensuite la conservation de la meilleure solution et les résultats d'optimisation soft, avant toute modification de l'algorithme.

## Analyse de reprise — 2026-10-17

### État vérifié
- Copie de lecture récupérée depuis `main`, commit `8d54f70a7e4ef1ec94c55d7e4307631dcb38aa2b` (ajout documentaire du présent fichier). Dernier changement de code : `ea57783`, 2026-06-14.
- Environ 12 448 lignes Python dans `src/creche_planning/`, dont 6 606 dans `solver.py` : les quelque 6 000 lignes correspondent au solveur seul.
- La configuration référence déjà `tests/fixtures/planning_gwendo_reference_valid.json` comme solution initiale : une installation neuve peut donc retrouver cette référence malgré l'absence des sorties locales.
- Revalidation réellement exécutée sur cette référence avec les paramètres de validation de la configuration actuelle : `status: ok`, `checks.errors: []`, score `15630`.
- Le code protège la référence revalidée, utilise CP-SAT pour chercher une amélioration, compare les scores et conserve la référence si le résultat final est invalide ou moins bon.
- Le score de comparaison `planning_quality_score` pénalise les sites/groupes multiples et le nombre de blocs. Il ne mesure pas directement tous les critères soft annoncés (durée des coupures, préférences horaires, marge de couverture). Point à examiner avant une évolution de l'optimisation.

### Contrôles
- Python 3.12.14, environnement Linux : `python -B -m unittest discover -s tests -v`.
- 28 tests exécutés : 26 réussis, 2 échecs dans `test_cp_sat_reference.py`.
- Cause vérifiée des deux échecs : `OR-Tools indisponible: No module named 'ortools'`. Le moteur renvoie alors `infeasible_or_not_solved`. Ce résultat ne démontre pas une infaisabilité métier.
- `requirements.txt` ne déclare toujours que NumPy et SciPy ; OR-Tools est absent de cet environnement.
- Les valeurs par défaut de `verify_solution` diffèrent de la configuration (tolérance de 3 % contre 5 %, coupure maximale de 90 minutes contre aucune limite hard). Les utiliser seules produit des erreurs sur la référence ; la revalidation ci-dessus applique bien la configuration du lancement.
- Aucun calcul autonome complet ni lancement réel de l'interface Windows effectué. Le test d'arrêt Windows est simulé par mocks et ne constitue pas une validation sous Windows.

### Changements et blocages
- Aucun code, test, donnée métier ou paramètre modifié. Seul ce compte rendu est ajouté à `PROJECT_STATE.md`.
- Aucun `AGENTS.md` ni `MODEL_GUIDE.md` trouvé dans l'arborescence du dépôt ; aucun accès Brain disponible parmi les outils exposés.
- Validation CP-SAT bloquée ici par l'absence d'OR-Tools ; les 28 tests ne peuvent pas être déclarés réussis.

### Prochaine action
Reconstituer un environnement avec OR-Tools, relancer les 28 tests puis un calcul borné sur une copie isolée. Vérifier la conservation du score 15630 et des contraintes hard avant toute modification du solveur.


## Résultats actualisés — 17 octobre 2026

Cette section remplace les conclusions provisoires ci-dessus sur l’environnement et les prochaines actions. Aucun code, test, donnée métier ou configuration n’a été modifié.

### Vérifications terminées
- OR-Tools 9.15.6755 installé dans un environnement Python 3.12 isolé.
- **28 tests sur 28 réussis**, en 1,748 seconde, avec `python -m unittest discover -s tests -v`.
- Les deux tests CP-SAT fixent le planning de référence : ils vérifient sa faisabilité, pas la génération libre.
- Référence revalidée : aucune erreur ; score de comparaison 15630.
- Essai sans indice initial et sans planning fixé, budget 100 secondes : aucune solution trouvée, statut `UNKNOWN`, durée totale 101,016 secondes. **Ce résultat ne prouve pas l’impossibilité de produire un horaire.** L’optimisation n’a pas commencé.
- Aucun lancement réel sous Windows effectué.

### Revue du solveur et du validateur

Le **solveur** fabrique l’horaire ; le **validateur** contrôle le résultat. La revue porte sur le moteur compact CP-SAT (`make_ortools_slot_payload`) et `verify_solution` dans `src/creche_planning/solver.py`, avec les helpers de `domain.py` et les règles de `docs/REGLES_METIER.md`. Les autres moteurs ne sont pas intégralement audités.

Les règles de couverture utilisent le même calcul des besoins. Les contrôles des groupes principaux, des colloques et des changements ordinaires par demi-journée sont présents des deux côtés. Cela ne constitue pas une preuve d’équivalence complète.

**Écarts confirmés par cinq petits exemples exécutés en mémoire :**

| Sujet | Exemple | Validateur | CP-SAT avec cet horaire fixé |
| --- | --- | --- | --- |
| Nombre de périodes | Contrat de 3 h, sans THE : lundi 08–09, 10–11 et 13–14 | Aucune erreur | Refus : au plus deux périodes |
| Chevauchements | Contrat de 3 h, sans THE : 08–10 et 09–10, durées déclarées 2 h + 1 h | Aucune erreur | Refus : présence unique par créneau et seulement 2 h distinctes |
| Durée incohérente | Contrat de 3 h, sans THE : 08–12, mais champ `hours=3` | Aucune erreur | Refus : les horaires représentent 4 h |
| THE et minimum de jours | Contrat de 9 h, THE arrondi à 1 h, sans colloque : lundi 08–16 | Aucune erreur : 8 h enfants + 1 h THE invisible | Refus : le minimum de jours est calculé sur 9 h / 8,5 h, soit deux jours |
| Jours hors groupe principal | Contrat de 10 h sans THE, groupe principal A imposé : lundi et mardi 08–13 en B ; limite d’exception 1 | Aucune erreur | Refus : deux jours hors groupe principal |

Précisions :
- Les microcas n’ont pas de besoin de couverture imposé, afin d’isoler les divergences. Tolérance hebdomadaire nulle, maximum journalier 8,5 h et absence de limite hard de coupure.
- Pour le dernier exemple, la personne participe aux colloques mais aucun colloque n’est défini. Le solveur limite à la fois les jours avec plusieurs groupes et les jours hors groupe principal ; le validateur ne limite que les premiers. **Le sens métier voulu doit être clarifié avant correction.**
- Le validateur additionne le champ `hours` pour les totaux, sans le recouper avec les heures de début et de fin. Il ne détecte pas non plus les chevauchements ni le dépassement des deux périodes de présence.
- Le minimum de jours du solveur compte du THE invisible comme s’il nécessitait de la présence. C’est une restriction supplémentaire reproduite sur un temps partiel ; son impact sur les données Gwendo reste à mesurer.

### Conséquences et limites
- Ces écarts sont reproduits ; **ils ne démontrent pas que le planning actuel est incorrect**.
- Ils ne démontrent pas non plus la cause du délai de recherche. Aucun diagnostic de performance complet n’a été effectué.
- Aucun correctif appliqué. Les sondes n’ont pas été ajoutées aux tests du dépôt.
- L’installation d’OR-Tools reste à déclarer dans les dépendances lors d’une future modification autorisée.

### Prochaine action
Préparer des corrections ciblées des contrôles de cohérence du validateur et du minimum de jours avec THE. Clarifier la règle des jours hors groupe principal avant de la modifier. Ne pas relancer de calcul long sans hypothèse précise.

## Décision métier — 17 octobre 2026

Clarification de Frédéric, consignée dans `docs/REGLES_METIER.md` :
- Une journée entière dans un autre groupe que le groupe principal reste possible, si les autres contraintes le permettent. Elle ne compte pas à elle seule comme une journée avec changement de groupe.
- La limite des journées exceptionnelles porte sur les changements en cours de journée ; une matinée dans un groupe et un après-midi dans un autre est possible.
- Une interdiction de groupe hard doit bloquer les affectations ordinaires dans ce groupe, pas uniquement son choix comme groupe principal. Une préférence négative soft doit pénaliser ces affectations.
- L'articulation avec les remplacements de colloque n'est pas encore précisée : aucune exception supplémentaire n'a été inventée.
- Les autres règles, notamment la présence au colloque du groupe principal, restent applicables.

**État : documentation mise à jour ; code inchangé.** La restriction CP-SAT sur les jours hors groupe principal et le traitement des interdictions de groupe doivent être revus selon cette clarification. Les contrôles manquants du validateur et le calcul du minimum de jours avec THE restent à corriger.

Contrôle : relecture des documents publiés ; aucun nouveau calcul ni test nécessaire pour cette modification documentaire. Prochaine action : poursuivre la revue selon ces règles explicites ; toute correction de code reste hors du périmètre actuel.

## Essai d’optimisation de cinq minutes — 17 octobre 2026

### Conditions
- Essai demandé par Frédéric : budget de 300 secondes, code inchangé.
- Planning de référence fourni comme **indice initial** (`hint_payload`), sans figer les affectations (`fixed_schedule=None`).
- Paramètres de validation identiques à ceux des essais précédents : tolérance hebdomadaire 5 %, THE 10 % avec colloques, plafond 40 h, maximum de jours actif, pas de limite hard de coupure.
- Les clarifications métier documentées aujourd’hui ne sont pas encore implémentées : cet essai mesure le code existant.

### Résultats vérifiés
- Durée totale : **300,953 secondes**.
- Première solution validée en **8,763 secondes**, score de comparaison **15630**, aucune erreur.
- Optimisation : **292,092 secondes**, statut `FEASIBLE`, 34 solutions signalées par le solveur.
- Objectif interne : **809618 → 631977**. Les améliorations arrivent par paliers, y compris après plusieurs dizaines de secondes sans progrès.
- Le candidat final de la phase d’optimisation passe le validateur (`validation hard_errors=0` dans le journal), mais il n’est pas retenu.
- Résultat renvoyé : **planning identique à la référence**, score **15630**, `status=ok`. Nouvelle vérification indépendante par `verify_solution` : aucune erreur.
- Aucun optimal global prouvé. Aucun fichier de planning actif remplacé ; aucun code, configuration ou donnée métier modifié.

### Conclusion
Le solveur sait améliorer son objectif interne à partir de la référence. Cependant, cette amélioration n’est pas alignée avec le score `planning_quality_score` utilisé pour sélectionner le résultat : le programme minimise un objectif pendant la recherche, puis compare les candidats avec un autre critère.

Dans ce lancement, le candidat optimisé est valide mais moins bon selon le second score : c’est déduit de la branche de sélection existante (candidat valide, statut d’optimisation FEASIBLE, pas de remplacement du premier candidat). Sa valeur exacte de `planning_quality_score` n’est pas journalisée : **inconnue**. Le programme conserve donc correctement la première solution, identique à la référence.

Cela explique l’absence de progrès du **résultat retenu dans cet essai** malgré les améliorations internes. Ce n’est pas une preuve de la cause du délai de génération sans référence.

### Prochaine action
Examiner et aligner les critères de qualité de la recherche et de la sélection, en tenant compte des règles métier clarifiées, avant de consacrer davantage de temps à des calculs longs. Aucune modification d’algorithme n’est encore autorisée dans le périmètre actuel.

## Correctif du validateur — 17 octobre 2026

### Autorisation et périmètre
Frédéric a demandé de passer aux corrections et laissé le choix de l'ordre. La restriction documentaire précédente (« code inchangé / correction hors périmètre ») est donc levée pour ces corrections ciblées. Premier lot : cohérence des périodes dans `verify_solution`.

### Changements
- Rejet des chevauchements entre les blocs d'une personne, y compris les colloques.
- Rejet des durées `hours` différentes de la durée début–fin arrondie à deux décimales, comme les exports existants.
- Rejet des plages de durée nulle ou négative.
- Maximum de deux périodes de présence continues par jour, comme CP-SAT. Les enregistrements adjacents sont fusionnés pour ce contrôle : un changement de groupe, un colloque ou un remplacement ne crée pas artificiellement une coupure.
- Sept tests de régression ajoutés dans `tests/test_validator_presence.py` : trois anomalies reproduites dans la revue, plages inversées, périodes adjacentes non triées, deux périodes permises et colloque au milieu d'une présence continue.

### Contrôles vérifiés
- `python -m unittest discover -s tests -v` : **35 tests réussis**, en 1,570 seconde, environnement Python isolé avec OR-Tools utilisé pour les essais précédents.
- Les deux tests CP-SAT reproduisent toujours la référence avec le validateur renforcé, sans erreur.
- Aucun calcul long relancé ; aucune donnée métier, configuration ou sortie active modifiée. Pas de validation réelle sous Windows.

### Reste à traiter / prochaine action
Le minimum de jours avec THE invisible, les jours entiers hors groupe principal, les interdictions de groupe et l'écart des objectifs restent ouverts. Prochaine action : corriger le minimum de jours avec THE par un microcas de régression, puis appliquer la clarification métier sur les journées hors groupe principal. L'exception des interdictions lors des remplacements de colloque demeure non précisée. L'alignement des scores doit s'appuyer sur la spec avant une nouvelle optimisation longue.

## Vérification complémentaire du validateur — 17 octobre 2026

### État vérifié et changements
- Le correctif de cohérence des périodes est publié dans le commit `274bac802c00aeeef7b396233abf087345f3dd64` ; aucun autre changement du solveur dans ce complément.
- Trois tests ajoutés : chevauchement avec un colloque, chevauchements imbriqués et plage de durée nulle. Le test de continuité autour d'un colloque vérifie maintenant l'absence de toute erreur sur un contrat cohérent, au lieu de ne vérifier que le compteur de périodes.

### Contrôles
- Les dix tests ciblés ont été exécutés sur le code antérieur au correctif (`0966437`) dans une copie temporaire : sept échecs reproduisent les anomalies, trois cas autorisés passent.
- Sur le code corrigé : **38 tests réussis**, en 1,515 seconde, avec Python 3.12.14 et OR-Tools 9.15.6755. Les deux tests CP-SAT de la référence restent réussis.
- `git diff --check` : aucune erreur. Données métier, configuration et planning de référence inchangés ; aucun essai long relancé.

### Limites et prochaine action
Ce lot corrige les contrôles des périodes ; il ne démontre pas l'équivalence complète du solveur et du validateur. Les écarts THE, affectations de groupe et critères de qualité restent ouverts, ainsi que la vérification réelle sous Windows. Prochaine correction : le minimum de jours calculé avec le THE invisible, à isoler par un test de régression avant modification.

## Correctif des jours avec changement de groupe — 17 octobre 2026

### Décision et changement
- Frédéric choisit de traiter maintenant les jours de changement de groupe. Cette priorité remplace la prochaine action proposée ci-dessus sur le THE.
- Dans `make_ortools_slot_payload`, suppression du plafond hard sur le nombre de jours hors groupe principal. La limite `max_weekly_group_exception_days` porte uniquement sur les jours avec plusieurs groupes ordinaires (`mixed_day`), comme dans le validateur.
- Les pénalités soft hors groupe principal, les contraintes des colloques et la stabilité dans chaque demi-journée restent en place. L'exception hebdomadaire existante pour les personnes ne participant pas aux colloques est conservée.
- `docs/REGLES_METIER.md` décrit désormais l'état d'application de ce correctif.

### Tests et état vérifié
- Six tests ajoutés dans `tests/test_cp_sat_group_days.py`, avec plannings fixés, THE désactivé et contrat de 10 h pour isoler cette règle.
- Avant correction : trois assertions échouent (deux journées entières hors groupe principal avec limite 0 puis 1, et une journée entière plus une journée mixte avec limite 1). Le validateur accepte ces cas, CP-SAT les déclare `INFEASIBLE`.
- Après correction, solveur et validateur acceptent ces cas. Ils refusent toujours deux jours mixtes avec limite 1, un jour mixte avec limite 0 et un changement ordinaire dans une même demi-journée. L'exception des non-participants aux colloques reste acceptée.
- Suite complète : **44 tests réussis**, en 1,776 seconde, avec Python 3.12.14 et OR-Tools 9.15.6755. Les deux tests de référence CP-SAT passent avec les contrôles renforcés.
- La contrainte hebdomadaire de `pattern_mip.py` utilise déjà les patrons mixtes (`pattern_mixed`) : contrôle par lecture, sans audit complet de ce moteur ni des moteurs historiques.
- `git diff --check` sans erreur. Données métier, configuration et planning de référence inchangés. Aucun essai long ni lancement réel sous Windows.

### Points ouverts et prochaine action
Ce correctif retire une restriction indue ; son effet sur la vitesse ou la qualité d'un calcul libre n'a pas été mesuré. Restent le minimum de jours avec THE invisible, les interdictions hard de groupe appliquées aux affectations ordinaires, et l'alignement des scores. Prochaine action proposée : corriger le calcul des jours avec THE par un microcas ciblé. L'exception éventuelle des interdictions de groupe pendant les remplacements de colloque reste à clarifier avant de modifier ce cas.

## Nouvel essai de cinq minutes après correctifs — 17 octobre 2026

### Conditions et contrôles
- Essai demandé par Frédéric sur le code publié `8d676ba`, budget 300 secondes, référence comme indice initial et `fixed_schedule=None`.
- Même référence et mêmes paramètres de validation que l'essai précédent : tolérance 5 %, THE 10 % avec colloques, plafond 40 h, maximum de jours actif, pas de limite hard de coupure. Pondérations du moteur compact conservées ; aucun changement de code de production pour cet essai.
- Le script observe les deux appels de `planning_quality_score` pour enregistrer les scores exacts et conserver les candidats évalués. Les fichiers d'essai sont séparés des sorties actives.
- Référence revalidée avant lancement. Résultat renvoyé et candidat optimisé revalidés indépendamment après le calcul : aucune erreur détectée par le validateur actuel.

### Résultats mesurés
| Mesure | Essai précédent | Après correctifs |
| --- | --- | --- |
| Durée totale (secondes) | 300,953 | 301,093 |
| Première solution validée (secondes depuis lancement) | 8,763 | 8,806 |
| Candidats signalés pendant l'optimisation | 34 | 30 |
| Objectif interne initial → final | 809618 → 631977 | 809618 → 650975 |
| Score de sélection du candidat optimisé | inconnu | 25720 |
| Score du planning renvoyé | 15630 | 15630 |
| Planning renvoyé identique à la référence | oui | oui |

- Statut final CP-SAT : `FEASIBLE`, pas de preuve d'optimalité. Phase de faisabilité : 8,076 s ; optimisation : 292,153 s.
- 17004 variables et 51523 contraintes contre 51534 contraintes précédemment.
- Les corrections n'ont pas amélioré le planning retenu dans cet essai. La recherche utilise plusieurs workers et un seul lancement par version : ces valeurs ne prouvent ni un gain ni une régression de performance.

### Écart de score désormais expliqué sur ce candidat
Le score de sélection augmente exactement de **10090** : une journée à plus de trois enregistrements ajoute 10000 points, un enregistrement supplémentaire ajoute 10 points et un enregistrement au-delà du premier dans la journée ajoute 80 points. Les nombres de groupes et de sites distincts restent identiques.

Dans le candidat optimisé, Priscila travaille mardi 08:30–12:00 puis 13:00–18:00. La seconde période se décompose en Nurserie 13:00–13:15, remplacement de colloque chez les Grands 13:15–14:00, puis Nurserie 14:00–18:00. Cela représente **deux périodes de présence, mais quatre enregistrements**. Le validateur accepte cette structure ; `planning_quality_score` la pénalise comme une journée à plus de trois blocs. L'absence d'alignement des objectifs est donc constatée avec ses valeurs exactes, et cette pénalité de représentation explique la différence de score pour ce candidat. Son caractère souhaitable doit être confronté aux priorités métier avant correction.

### Trace, limites et prochaine action
- Conditions avec empreintes des entrées, résumé, journal et candidat optimisé sauvegardés dans `docs/experiments/2026-10-17-group-days-300s/`.
- Aucun planning actif, donnée métier ou paramètre remplacé. Le planning renvoyé reste la référence. Les 44 tests précédemment réussis n'ont pas été relancés : aucun code de production n'a changé pendant l'essai.
- Les écarts connus sur le THE et les interdictions de groupe restent ouverts ; « aucune erreur » désigne les contrôles actuels, pas une preuve d'application complète de la spec.
- Prochaine action recommandée : aligner les critères de qualité, en distinguant les périodes de présence des enregistrements d'activité, avant de prolonger l'optimisation. Aucune correction des scores appliquée dans cet essai.
