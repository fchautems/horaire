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


## Correctif du comptage dans le score de sélection — 17 octobre 2026

### Changements
- Correction demandée par Frédéric : `planning_quality_score` compte désormais les périodes de présence continues, en fusionnant les activités adjacentes ou chevauchantes après tri horaire, sans modifier le planning.
- Les pondérations, pénalités de groupes/sites et d'erreurs, ainsi que le seuil existant de plus de trois périodes dans le score, sont conservés. Le validateur continue d'interdire plus de deux périodes ; ce seuil soft n'est pas une autorisation hard.
- Six tests de régression ajoutés dans `tests/test_planning_quality_score.py` : remplacement fragmenté, colloque adjacent, vraie coupure, quatre périodes distinctes, intervalles imbriqués non triés sans mutation, journée vide et erreurs.

### Contrôles et état vérifié
- Avant correction : trois des six nouveaux tests échouent et reproduisent les pénalités artificielles.
- Après correction : **50 tests réussis**, en 1,768 seconde, avec l'environnement Python/OR-Tools existant. Les tests CP-SAT et de validation de la référence passent.
- Recalcul sur les horaires sauvegardés : référence **14280**, candidat optimisé de l'essai de cinq minutes **13560** (plus bas est meilleur). Ils étaient respectivement à 15630 et 25720 avec l'ancien comptage. Le candidat devient meilleur selon le score corrigé de 720 points.
- Les scores avant/après ne sont pas directement comparables : la métrique a changé. Aucun nouveau calcul d'optimisation lancé, aucun planning actif remplacé.
- `git diff --check` sans erreur pour les fichiers de ce lot. Aucun changement des données métier ou des contraintes hard ; pas de test réel sous Windows.

### Limites et prochaine action
- Le bug de fragmentation est corrigé ; l'alignement complet avec l'objectif interne CP-SAT reste ouvert, ainsi que les écarts THE et interdictions de groupe déjà documentés.
- Prochaine action : utiliser ce score corrigé lors du prochain essai autorisé ; ne pas interpréter le seul recalcul comme une nouvelle optimisation.


## Essai de cinq minutes avec score corrigé — 17 octobre 2026

### Conditions et résultat vérifié
- Lancement autorisé par Frédéric, code de production `79d11f2`, budget 300 secondes ; départ du candidat de l’essai précédent, score corrigé 13560, fourni comme indice sans affectations fixées.
- Mêmes options et pondérations que l’essai précédent. Durée totale 301,053 s ; première solution valide en 8,595 s ; cinq solutions signalées pendant l’optimisation.
- Objectif interne 650975 → 631977 ; score de sélection final du nouveau candidat 15780, contre 13560 pour le départ (plus bas est meilleur).
- Le programme a correctement conservé le planning de départ, identique, score 13560. Revalidation indépendante du résultat renvoyé et du candidat optimisé : aucune erreur selon les contrôles actuels.
- Aucun optimum prouvé (`FEASIBLE`). Aucun code de production, configuration, donnée métier ou planning actif remplacé. Les 50 tests déjà réussis ne sont pas relancés pour cet essai sans modification de code.

### Conclusion, limites et prochaine action
- Le correctif de fragmentation est opérationnel, mais il ne suffit pas à aligner le score de sélection sur l’objectif CP-SAT : cet essai améliore l’objectif interne et dégrade le score de sélection.
- Le meilleur planning connu selon le score corrigé reste à 13560, contre 14280 pour la référence historique. Aucun progrès supplémentaire retenu dans cet essai.
- Prochaine action : décomposer les contributions aux deux scores sur ces candidats, puis aligner les critères selon les priorités métier avant de prolonger les calculs. Les écarts THE et interdictions de groupe restent ouverts.
- Conditions, script, journaux, résumé et revalidation conservés dans `docs/experiments/2026-10-17-score-fixed-300s/`.


## Alignement du score de sélection sur le moteur compact — 17 octobre 2026

### Décision et changements
- Frédéric autorise la correction des deux calculs ensemble. Choix : conserver les critères/pondérations actuels du moteur compact CP-SAT et les utiliser pour sélectionner les plannings ; aucune nouvelle priorité métier introduite.
- Nouveau module `scoring.py` : coefficients communs et évaluation indépendante à partir des créneaux du planning. Le moteur lit ces mêmes coefficients pour construire son objectif.
- `planning_quality_score` utilise désormais ce calcul pour les résultats nouveaux/revalidés. Le lanceur compare tous les candidats, caches et checkpoints avec la configuration courante ; un ancien champ `objective` n'est jamais utilisé comme note fiable.
- Les caches reconstruisent leur contexte de score après revalidation. Champ JSON additionnel `quality_scoring`, formats d'affectation conservés. Compatibilité de l'appel de bas niveau sans contexte sur JSON ancien documentée dans `docs/QUALITY_SCORING.md`.
- Écart aux heures cibles calculé par une valeur absolue exacte dans le modèle, évitant des variables de surplus/déficit simultanément positives lors de la première faisabilité. Aucun horaire autorisé supprimé par ce changement auxiliaire.

### Contrôles vérifiés
- **55 tests réussis**, en 7,210 secondes, dont cinq nouveaux tests d'alignement. Le test d'orchestration simulé fournit maintenant les champs de contrat/groupe nécessaires au calcul.
- Trois horaires sauvegardés ont été fixés dans CP-SAT pour comparer l'objectif du modèle avec le score recalculé depuis leurs affectations : référence historique **809618**, candidat du premier essai corrigé **650975**, dernier candidat **631977**. Égalité exacte dans chaque cas, aucune erreur du validateur.
- Le candidat à 631977, rejeté lors du dernier essai sous l'ancien critère de sélection, est désormais meilleur selon les deux calculs. Ceci est un reclassement d'horaires déjà obtenus, pas un nouveau progrès de recherche.
- Microcas avec pondérations non standard, préférences horaires positives/négatives et de groupe multiples, écart d'heures, jour mixte et travail hors groupe principal : notes identiques.
- Fragmenter une activité adjacente ne change pas la note. Un objectif stocké ou un ancien contexte de cache ne supplante pas la politique courante après revalidation.
- Recherche libre courte sur microcas : objectif et score des checkpoints/résultat identiques ; la sélection ne dégrade pas la première solution valide.
- `git diff --check` sans erreur. Aucun essai de cinq minutes relancé ; aucun planning actif, donnée métier ou configuration remplacé. Les tests Windows restent simulés.

### Limites et prochaine action
- Alignement couvert : objectif compact CP-SAT et sélection finale dans le lanceur. Les autres moteurs conservent leurs propres objectifs de recherche ; leurs candidats sont toutefois comparés par le score commun du lanceur.
- Les critères actuels sont conservés, pas déclarés exhaustifs de la spec. En particulier la durée des coupures n'est toujours pas un terme distinct de l'objectif compact (`split_gap_weight` inutilisé auparavant et inchangé). Les écarts THE/interdictions de groupe restent ouverts.
- Les scores 13560/15780 de l'ancien critère ne sont plus les valeurs du score commun. Prochaine étape possible : essai borné depuis le dernier candidat, score commun 631977, sans figer ses affectations ; aucun lancement long automatique effectué dans ce lot.


## Essai de cinq minutes avec scores alignés — 17 octobre 2026

### Conditions et état vérifié
- Essai autorisé depuis le candidat connu à 631977, code publié `68acb55`, budget de recherche 300 s, `fixed_schedule=None` : aucune affectation figée. Options et pondérations identiques aux essais précédents.
- Parité locale des fichiers du lot d'alignement contrôlée avant lancement. Aucune modification du code de production, des données métier, des paramètres ou des sorties actives.
- Durée totale 303,274 s (construction et validation comprises). Première solution valide à 16,247 s, score 631995 ; retour au score 631977 à 32,773 s. Deux candidats signalés pendant l'optimisation.
- Score commun du résultat **631977**, identique au départ ; objectif interne et score recalculé strictement égaux pour les deux candidats évalués (631995 puis 631977).
- Revalidation indépendante du départ et du résultat : aucune erreur selon le validateur actuel. Le résultat diffère du planning de départ mais toutes les contributions au score sont identiques. Il s'agit d'une alternative à qualité égale, sans amélioration.
- Statut `FEASIBLE` : aucune preuve d'optimalité. Le planning actif n'a pas été remplacé. Résultats, script, empreintes des entrées et journaux dans `docs/experiments/2026-10-17-aligned-300s/`.

### Contrôles, limites et prochaine action
- Assertions de l'essai réussies : absence d'erreur de validation, score final inférieur ou égal au départ, égalité score final/objectif interne. Les 55 tests précédemment réussis ne sont pas relancés : aucun code de production modifié.
- L'alignement est confirmé sur cette recherche réelle ; cinq minutes supplémentaires n'ont pas donné de progrès. Cela ne prouve pas que le planning est optimal.
- Les écarts THE/interdictions de groupe et l'absence de pénalité distincte sur la durée des coupures restent ouverts, comme documenté au lot précédent.
- Prochaine action possible : examiner les critères métier et la décomposition du score avant de décider d'un nouvel essai ; aucun calcul supplémentaire lancé automatiquement.


## Diagnostic des trois contributions principales — 17 octobre 2026

- Demande de Frédéric : expliquer les trois principaux postes du planning à 631977, sans nouveau calcul d’optimisation ni modification de code.
- Recalcul indépendant avec `compact_quality_breakdown` depuis `docs/experiments/2026-10-17-aligned-300s/result.json` : total exactement 631977, identique au résumé sauvegardé.
- Débuts de présence : 624000 = 52 périodes × 12000 ; 45 journées travaillées, donc sept périodes supplémentaires après coupure (84000 points). Ne pas présenter les 624000 points comme une pénalité uniquement sur les coupures. La durée des coupures ne figure pas séparément au score.
- Écart aux heures cibles enfants : 5000 = deux créneaux de quinze minutes d’écart absolu cumulés, soit trente minutes. Ce chiffre porte sur les cibles enfants utilisées dans l’objectif, pas directement sur un déficit contractuel total.
- Travail ordinaire hors groupe principal : 3240 au total (3200 pour une journée + 40 pour le couple groupe/journée).
- Autres contributions : créneaux enfants 1237 ; bonus de groupe principal préféré -1500 ; toutes les autres contributions nulles. Somme contrôlée.
- Aucun planning actif, code, paramètre ou donnée métier modifié ; aucun test ni recherche longue relancé pour cette lecture.
- Prochaine action possible : examiner la répartition des sept coupures et les contraintes qui les imposent, avant de décider d’un nouvel essai. Note locale de diagnostic, non publiée sur GitHub.


## Durées des sept coupures — 17 octobre 2026

- Lecture du résultat sauvegardé à 631977 ; fusion des activités adjacentes avant calcul des intervalles sans présence.
- Durées vérifiées par ordre décroissant : Léa jeudi 10:45–13:15 (150 min) ; Tara jeudi 11:00–13:15 (135 min) ; Emilie vendredi 12:00–14:15 (135 min) ; Natacha mardi 11:45–13:15 (90 min) ; Priscila mardi 12:00–13:15 (75 min) ; Magali lundi 12:00–13:00 et mercredi 12:30–13:30 (60 min chacune).
- Chaque reprise coûte 12000 points indépendamment de la durée. Le classement par durée est un indicateur de gêne potentielle, pas un classement par score ni une preuve de facilité de suppression.
- Aucun code, planning actif ou paramètre modifié, aucune recherche lancée. Prochaine action éventuelle : examiner la faisabilité de réorganisation des coupures retenues, sans oublier les pauses requises. Note locale non publiée.


## Essai ciblé Léa jeudi — 17 octobre 2026

- Essai de cinq minutes explicitement autorisé après explication : viser la suppression de la coupure de Léa le jeudi en conservant une meilleure note globale.
- Instrumentation expérimentale uniquement en mémoire, script conservé dans `docs/experiments/2026-10-17-lea-thursday-300s/run.py` : exactement une période de présence de Léa jeudi ; objectif commun <= 631976. Toutes les affectations restent libres ; aucun planning fixé, aucune règle métier assouplie. Le planning à 631977 sert d’indice. Cette restriction réduit volontairement le domaine de cet essai ciblé, pas celui du modèle de production.
- Résultat : 302,155 s au total ; CP-SAT `UNKNOWN`, zéro solution, 17060 branches, quatre conflits. Aucun candidat ni nouvelle note disponible, phase d’optimisation non engagée. Ce résultat ne prouve ni l’impossibilité de supprimer cette coupure ni l’optimalité du planning de départ.
- Le planning de départ a été revalidé avant le calcul. `selected.json` conserve ses affectations à l’identique ; aucune sortie active remplacée. Empreintes du solveur, du module de score et des données inchangées après le calcul. Aucun code de production modifié, aucune suite de tests relancée pour ce script expérimental.
- Conditions, journaux, résultat et résumé sauvegardés dans le dossier de l’essai. Le moteur actuel ne fait pas l’objet d’un audit des pauses réglementaires ; ne pas présenter cet essai comme une validation de celles-ci. Les limites THE/interdictions de groupe restent ouvertes.
- Prochaine action possible : isoler la faisabilité de Léa jeudi en une seule période sans exiger en même temps une meilleure note ; aucune nouvelle recherche lancée.

## Essai de faisabilité Léa jeudi sans coupure — 17 octobre 2026

### Résultat vérifié et fin de la reprise
- La relance complète a été retrouvée dans la copie de travail : journal, conditions, résultat et résumé cohérents. Aucun processus de calcul n'était encore actif. Le résultat était disponible localement mais n'avait pas été publié ; la cause de l'interruption initiale n'est pas établie.
- Recherche de faisabilité uniquement : exactement une période de présence pour Léa jeudi, sans imposer une amélioration du score, arrêt au premier candidat et budget de 300 secondes. Toutes les affectations restent libres et les contraintes métier existantes restent actives.
- Durée totale : **301,770 secondes**, dont **300,458 secondes** de recherche. Statut CP-SAT **UNKNOWN**, **zéro solution**, 166520 branches et 4796 conflits. Aucune phase d'optimisation engagée.
- **Conclusion : aucune solution trouvée dans ce délai ; l'impossibilité de supprimer la coupure n'est pas démontrée.** Retirer l'exigence d'une meilleure note n'a pas suffi à obtenir une réponse dans cet essai.
- Le planning conservé est identique au départ. Revalidation indépendante effectuée lors de cette reprise avec les options sauvegardées : aucune erreur du validateur actuel, score **631977**. Aucun planning actif remplacé.
- Empreintes SHA-256 du solveur, du score et des données conformes aux conditions enregistrées ; empreintes Git des trois fichiers identiques à celles de main au commit `c10800f`.
- Aucun nouveau calcul lancé inutilement : la relance autorisée avait déjà terminé ses cinq minutes. Aucun code de production ou donnée métier modifié. Script expérimental, conditions, journaux et résultats publiés dans `docs/experiments/2026-10-17-lea-feasibility-300s/`.

### Limites et prochaine action
- Les écarts connus THE/interdictions de groupe et l'absence d'audit des pauses réglementaires restent ouverts ; aucune nouvelle garantie métier n'est déduite de cet essai.
- Avant une autre recherche longue, examiner les contraintes concrètes de Léa le jeudi et leur interaction avec la couverture, ainsi que les restrictions déjà identifiées du modèle. Ce diagnostic doit distinguer une nécessité métier d'une restriction de modélisation. Aucun nouveau calcul long lancé automatiquement.


## Nouveau contrôle du planning de référence — 17 octobre 2026, 17 h (Suisse)

- Contrôle demandé par Frédéric avant toute nouvelle optimisation globale.
- Revalidation exécutée sur `docs/experiments/2026-10-17-lea-feasibility-300s/selected.json`, avec les options sauvegardées de cet essai, puis deuxième appel direct à `verify_solution` : statut `ok`, aucune erreur.
- Score recalculé avec le contexte reconstruit depuis les données actuelles : **631977**. Décomposition : débuts de présence 624000 ; créneaux enfants 1237 ; écart aux heures cibles 5000 ; hors groupe principal 3240 ; préférence du groupe principal -1500 ; autres termes nuls.
- Identité avec les fichiers de `main` vérifiée par empreinte Git pour `solver.py`, `scoring.py`, `domain.py` et `data/gwendo.json`. Les affectations sont inchangées par la revalidation. Aucun solveur ni test complet relancé, aucun code ou planning actif modifié.
- Conclusion : reprendre ce planning comme indice initial est compatible avec le code corrigé et sa note actuelle ; l'ancien score stocké n'a pas servi de référence au recalcul.
- Limites conservées : contrôles actuels seulement ; écarts THE/interdictions de groupe et audit des pauses encore ouverts. Cette vérification ne constitue pas un audit complet des règles métier.
- Prochaine action : la base est confirmée ; aucun nouvel essai ciblé Léa à poursuivre. Avant un calcul global supplémentaire, choisir un changement de stratégie motivé par les essais globaux déjà sans progrès ; aucun nouveau calcul long lancé dans ce contrôle.


## Recherche globale de cinq minutes — 17 octobre 2026, après 17 h Suisse

- Lancement explicitement autorisé par Frédéric depuis le planning revalidé à 631977. Aucune affectation fixée, aucune restriction spécifique à Léa, mêmes paramètres et pondérations que l'essai global précédent, budget 300 s.
- Résultat vérifié : **626975**, soit **5002 points de mieux** ; durée totale **301,103 s**, première solution valide à 9,173 s. Phase optimisation : 291,828 s, statut `FEASIBLE`, trois solutions signalées. Aucun optimum prouvé.
- Validation du résultat, puis appel indépendant à `verify_solution` avec les options enregistrées : aucune erreur selon les contrôles actuels. Égalité exacte entre objectif interne et score commun recalculé : 626975. Le résultat est différent du départ.
- Gain : terme d'écart aux heures cibles enfants 5000 → 0 ; terme des créneaux enfants 1237 → 1235. Autres contributions identiques : débuts de présence 624000, travail hors groupe principal 3240, préférence de groupe -1500. Les sept coupures restent présentes.
- Empreintes des fichiers de production, données, configuration et planning de départ inchangées après le calcul. Aucun code ni planning actif remplacé ; le résultat est sauvegardé comme nouveau meilleur candidat connu selon le score commun actuel.
- Script, conditions, journaux, résumé et planning complet regroupés dans `docs/experiments/2026-10-17-global-restart-300s/evidence.json` (dictionnaire de noms de fichiers et contenus UTF-8). Pour une reprise, lire la valeur `result.json`, puis revalider avec les options de `conditions.json` et le code courant.
- Pas de suite complète relancée : aucun code de production modifié. Limites THE/interdictions de groupe et audit des pauses inchangées ; aucune conformité métier exhaustive déduite de cette validation.
- Prochaine action : utiliser le nouveau candidat à 626975 comme référence revalidée pour toute suite autorisée ; ne pas poursuivre une restriction Léa ni relancer automatiquement un calcul long. L'essai global a apporté un progrès mesuré, sans suppression de coupure.


## Correctif du minimum de jours avec THE invisible — 17 octobre 2026

### Périmètre et changement
- Correctif explicitement demandé par Frédéric après priorisation du bug connu ; aucun nouveau calcul global d'optimisation lancé.
- Dans `make_ortools_slot_payload`, la borne inférieure redondante des jours de présence utilise désormais les heures enfants minimales : contrat moins tolérance moins THE, au lieu du contrat moins tolérance.
- Exemple reproduit : contrat 9 h, THE arrondi à 1 h et 8 h enfants le lundi. Avant correction, le validateur accepte mais CP-SAT impose à tort deux jours ; après correction, CP-SAT accepte cette journée unique.
- Les colloques visibles restent liés aux variables de présence et aux limites journalières. La borne ne les efface pas : leurs contraintes imposent toujours leur présence effective.
- Les plafonds de jours, durées journalières, heures contractuelles, règles de groupes et pondérations du score ne sont pas modifiés. Les autres moteurs ne sont pas modifiés dans ce lot.

### Contrôles vérifiés
- Cinq tests ajoutés dans `tests/test_cp_sat_the_work_days.py` : THE invisible sans jour supplémentaire ; tolérance hebdomadaire ; contrat sans THE ; plafond journalier ; présence obligatoire au colloque.
- Avant correction : deux tests échouent et reproduisent le refus incorrect de CP-SAT ; les trois contrôles de contraintes conservées passent.
- Après correction : **60 tests réussis en 7,455 secondes**, Python 3.12 / OR-Tools 9.15.6755, y compris les tests CP-SAT de référence et d'alignement des scores.
- Meilleur candidat à **626975** extrait des preuves du dernier essai global : revalidation indépendante sans erreur, puis reproduction à affectations fixées dans CP-SAT avec le code corrigé. Objectif et score recalculé égaux à **626975**. Le statut OPTIMAL de cette reproduction fixe ne prouve pas l'optimalité du planning libre.
- Parité du code et des tests locaux avec la version GitHub de départ contrôlée avant publication, hors correctif ; données et configuration identiques. Contrôle des espaces de fin de ligne et `git diff --no-index --check` réussis.

### Limites et prochaine action
- Aucun planning actif ni donnée métier modifié. Aucun gain de score ou de vitesse n'est revendiqué : correction d'une restriction erronée, pas nouvel essai d'optimisation. Pas de validation réelle sous Windows.
- L'écart connu sur les interdictions de groupe et l'audit des pauses restent ouverts. Le bug de minimum de jours CP-SAT lié au THE invisible est corrigé.
- Prochaine action recommandée : traiter séparément les interdictions de groupe selon les règles métier documentées, en explicitant le cas encore non tranché des remplacements de colloque, avant de multiplier les recherches longues.


## Audit global — 18 octobre 2026 (Suisse)

### État vérifié
- Audit demandé par Frédéric sur l’ensemble du code, sans nouvelle correction ni optimisation globale. Version de départ confirmée sur GitHub : `882209d75cfba2a8ac09eb3ed6a2e788705c6869`.
- Inventaire : dix modules, trois lanceurs Python, deux lanceurs Windows ; 12 675 lignes Python de production et 253 fonctions, fonctions imbriquées comprises. Revue approfondie du chemin actif et structurelle des chemins historiques.
- Suite existante exécutée : **60 tests réussis en 7,483 s**. **31 scénarios ciblés** d’audit ajoutés séparément des tests de production ; les résultats caractérisent les comportements observés, y compris les défauts.
- Rapport : `docs/audits/2026-10-18/AUDIT_GLOBAL_2026-10-18.md`, avec **27 anomalies ou écarts techniques confirmés**, huit prioritaires, quatre questions métier et cinq risques distincts. Scénarios, assertions, résultats et inventaire des sources joints. Ce nombre n’est pas un nombre d’erreurs dans le planning actuel.
- Candidat conservé : validation actuelle sans erreur, contrôles structurels indépendants sans anomalie, score **626975** avec sa politique expérimentale. La pondération du lanceur pour les jours travaillés porte la note du même candidat à **829475** ; différence de politique, pas régression du planning. Un remplacement en Grands le mardi finit à 14:15 alors que le colloque finit à 14:00 ; l’extension d’exception autour des colloques reste à valider.

### Changements et contrôles
- Ajout documentaire et scénarios de reproduction seulement. Aucun code de production, donnée métier, paramètre, planning actif ni sortie d’optimisation remplacé.
- Défauts prioritaires reproduits : interdiction hard de groupe contournée ; ancien employé compté par un cache ; activités de colloque non authentifiées ; groupes principaux absents contournant les contrôles ; candidat moins bon retenu sur le chemin `ortools` ; cache malformé levant une exception ; coupures matinales exclues des patrons ; représentation incompatible des remplacements entre moteurs.
- Repli patrons inaccessible avec le budget courant de 100 s confirmé par simulation de l’orchestration. Autres écarts : profils/critères soft, colloques multiples ou simultanés, schéma, NaN, THE, alias de types, staffing, ouvertures, éditeur, rapports, dépendances et budget de construction.

### Limites et prochaine action
- Pas de garantie d’absence d’autres bugs, pas de contrôle réglementaire externe, de test graphique réel ou Windows réel, ni d’équivalence exhaustive des moteurs historiques. Aucun pourcentage de couverture revendiqué.
- Les règles positives hard sur une plage ne sont pas déclarées erronées : les données actuelles emploient des plages sur la journée entière, compatibles avec une exigence de présence partielle. Pourcentages de qualification instantanés ou hebdomadaires, exceptions de remplacement et pauses/déplacements restent à préciser.
- Aucun `AGENTS.md` ou `MODEL_GUIDE.md` trouvé dans les emplacements accessibles inspectés ; aucun outil Brain disponible identifié.
- Prochaine action recommandée : corriger d’abord les garde-fous du validateur et des caches, puis les différences de moteurs et la politique de score, avec tests de régression ; ne pas relancer des optimisations longues pour traiter ces défauts. Les règles métier ambiguës doivent être clarifiées séparément.

## Corrections de l’audit — 18 octobre 2026, en cours

- Autorisation : Frédéric demande de corriger tous les bugs identifiés et de poursuivre jusqu’aux vérifications finales.
- Base : `b036113`, copie isolée `fix/audit-2026-10-18`, audit A01–A27 et risques R01–R05 relus.
- Données métier et plannings de référence conservés. Questions Q01–Q04 séparées des défauts techniques ; conventions existantes conservées tant qu’aucune décision contraire n’est donnée.
- Aucun AGENTS.md / MODEL_GUIDE.md trouvé dans les emplacements accessibles ; aucun outil Brain disponible.
- Environnement rétabli avec OR-Tools 9.15.6755 ; contrôle initial en cours.
- Prochaine action : fermer les trous du validateur et des caches, puis traiter moteurs, qualité, interface et sauvegardes.


### Avancement vérifié des corrections — 18 octobre 2026

- Les 27 constats ont été traités en code ou consignés avec leur limite de support dans docs/audits/2026-10-18/CORRECTIONS.md. A19 est désormais clarifié par la décision métier du 18 octobre ci-dessous. Les limites de support et de validation restent documentées.
- Validation renforcée des identités, blocs, groupes, activités et caches ; garde-fou commun aux moteurs ; quotas artificiels de remplacement retirés ; domaine des coupures élargi ; budgets et paramètres de qualité corrigés ; sauvegardes atomiques par fichier et garde-fous interface.
- **93 tests réussis en 11.428 secondes** lors du contrôle final, avec OR-Tools 9.15.6755 et Python 3.12. Les sondes historiques d’audit ne sont pas réécrites en tests de succès.
- Meilleur candidat revalidé : aucune erreur, score historique 626975 ; reproduction fixe avec critères corrigés 646975, dont 20000 de durée de coupure. Aucun changement d’affectation ou de planning actif ; pas d’optimisation globale.
- Limites : certains cas/options sont refusés explicitement par les patrons et pris en charge par le compact ; exports atomiques individuellement, sans transaction commune ; appels natifs et interface non validés en situation réelle Windows.
- Contrôles finaux : compilation des modules et git diff --check réussis. La décision A19 est consignée ci-dessous ; conserver les conventions Q01–Q04.


## Décision métier sur les heures d’ouverture — 18 octobre 2026

- Frédéric confirme explicitement qu’une éducatrice peut travailler avant l’ouverture ou après la fermeture, pour préparer l’accueil ou ranger. Les horaires d’un site ne sont donc pas des bornes hard de présence.
- A19 clos par clarification métier : ne pas ajouter l’interdiction envisagée. Règle ajoutée à docs/REGLES_METIER.md et suivi mis à jour dans docs/audits/2026-10-18/CORRECTIONS.md.
- Documentation métier actualisée également pour les correctifs déjà publiés : interdictions hard appliquées aux affectations ordinaires ; remplacement selon la couverture effectivement perdue, sans quota par groupe source, conformément aux décisions existantes.
- Aucun code, donnée, horizon de calcul ou planning modifié ; aucun test ni calcul relancé pour cette clarification documentaire. La dernière suite reste à 93 tests réussis. L’autorisation de présence hors ouverture n’élargit pas automatiquement l’horizon global du programme.
- Les conventions Q01–Q04 et les limites techniques décrites dans le suivi restent distinctes ; aucune garantie exhaustive ou réglementaire nouvelle. Prochaine action : reprendre le suivi publié si une nouvelle étape est demandée.


## Précisions métier Q02–Q04 — 18 octobre 2026

- Réponses explicites de Frédéric : Q02 = semaine ; Q03 = oui à la fenêtre -15/+30 minutes, n’importe qui peut remplacer, non à l’application des interdictions de groupe pendant un remplacement ; Q04 = pas de repos minimum entre deux jours, dix minutes de déplacement entre sites.
- Ces décisions sont consignées dans docs/REGLES_METIER.md. Q01 reste ouvert et est réexpliqué avec une présence 9–10 dans une fenêtre 8–12. Les pauses au sein d’une journée ne sont pas définies par la réponse sur le repos entre journées.
- Aucun code, donnée ou planning modifié, aucun test relancé pour cette documentation. Les 93 tests précédents ne valident pas encore la nouvelle règle des déplacements.
- Prochaine action technique : imposer les dix minutes entre sites, harmoniser le contrôle final et les moteurs concernés, puis revalider les candidats. La grille de quinze minutes doit être traitée explicitement sans arrondir le minimum à zéro. Ne pas déclarer le meilleur candidat conforme à cette nouvelle règle avant contrôle.


## Contrôle de l’essai depuis zéro — 18 octobre 2026

- Recherche autorisée de 600 secondes : lors du précédent contrôle, le processus 3471 était actif à environ 136 secondes et utilisait le CPU.
- Lors du contrôle suivant, le processus n’est plus visible et aucun result.json, summary.json ou checkpoint n’est présent dans le dossier local de l’essai. Dernière étape journalisée : recherche générale commencée à 91,150 secondes, sans fin enregistrée.
- L’essai est interrompu sans résultat final exploitable ; ni la consommation complète des 600 secondes ni l’infaisabilité du problème ne sont établies. Cause de terminaison inconnue.
- Aucun nouveau calcul lancé lors du contrôle, aucun planning remplacé. Les modifications locales liées aux déplacements ne sont pas déclarées publiées dans cette note.
- Prochaine action : diagnostiquer la terminaison et la persistance du processus avant une relance identique. La clarification ultérieure Q01 du dialogue confirme une présence partielle dans la fenêtre : la règle positive hard actuelle doit être conservée.


## Déplacements corrigés et nouvel essai — 18 octobre 2026

- Q01 confirmé : une obligation horaire positive hard exige une présence partielle dans la fenêtre, pas la fenêtre entière. Comportement existant conservé.
- Dix minutes minimum entre sites, zéro minute entre groupes du même site, colloques et remplacements compris : ajout au validateur, au CP-SAT compact et aux patrons. Sur la grille de quinze minutes, un créneau vide est nécessaire entre sites.
- **103 tests réussis en 12,157 secondes**, Python 3.12 / OR-Tools 9.15.6755 ; git diff --check réussi. Les références historiques avec déplacements instantanés sont désormais rejetées ; elles sont conservées pour traçabilité.
- Relance explicite demandée : recherche de 600 secondes sans ancien planning fourni comme hint et sans planning fixé. Les heuristiques internes de groupes restent actives, sans fixation permanente des groupes principaux.
- Essai démarré le 18 octobre à 12:24:20 UTC ; suivi du processus avec battement toutes les quinze secondes et enregistrement du code de sortie. Dossier : docs/experiments/2026-10-18-from-zero-600s-retry/. Aucun nouveau résultat au contrôle à 150 secondes ; l'ancien essai interrompu reste distinct.
- État temporaire : recherche en cours. Aucun planning actif remplacé. La note de résultat finale doit être ajoutée à la fin réelle de cet essai.


## Résultat final de la relance de dix minutes — 18 octobre 2026

- Recherche terminée normalement : **600,622 secondes**, code de sortie **0**, statut CP-SAT **UNKNOWN**, aucune solution ni checkpoint. L'infaisabilité n'est pas démontrée. La note temporaire « recherche en cours » ci-dessus est close.
- Recherche réellement suivie jusqu'à la fin : six essais de groupes, recherche générale automatique (360,295 s), portfolio (149,165 s). Aucun planning ancien fourni en hint et aucun planning fixé ; heuristiques internes de groupes conservées, hypothèses libérées avant recherche générale.
- Ancien planning revalidé : **sept déplacements intersites sans délai**, donc référence invalide sous la nouvelle règle, conservée séparément. Aucun planning actif remplacé.
- Corrections publiées dans bdb9e01878b901941ec53bf2637887b724d884b8. Les 103 tests passent ; empreintes des sources, données et configuration identiques avant/après calcul.
- Résumé et preuves : docs/experiments/2026-10-18-from-zero-600s-retry/README.md, summary.json et evidence.json. Premier essai interrompu conservé séparément dans le dossier voisin sans suffixe.
- Prochaine piste technique : réparation ciblée de la référence historique ou diagnostic des contraintes de déplacements pour obtenir un premier candidat valide. Aucun nouveau calcul lancé après cet essai demandé.


## Recherche guidée autorisée — 18 octobre 2026

- Frédéric demande le lancement après clarification : l'ancien planning sert de point de départ, sans fixer les horaires ni les affectations ; les contraintes métier restent inchangées.
- Budget : 600 secondes, même moteur compact CP-SAT et mêmes options que l'essai depuis zéro. Seule différence de recherche : hint_payload reçoit le candidat historique ; fixed_schedule reste None. Aucune modification du code de production ni de la configuration.
- Dossier distinct : docs/experiments/2026-10-18-guided-600s/. Suivi du processus jusqu'au résultat avec enregistrement du code de sortie et conservation de chaque candidat validé.
- Environnement vérifié : OR-Tools 9.15.6755 disponible dans une cible isolée. Aucun MODEL_GUIDE.md ou AGENTS.md trouvé dans /workspace ; aucun outil Brain disponible identifié.
- État temporaire : essai prêt à lancer. Prochaine action : exécuter, revalider tout candidat, puis consigner le résultat réel.


## Résultat final de la recherche guidée — 18 octobre 2026

- Essai demandé par Frédéric terminé normalement : **600,518 secondes**, code de sortie **0**, statut **UNKNOWN**, zéro solution et aucun checkpoint. La note temporaire de préparation ci-dessus est close. L'infaisabilité et l'existence d'un nouveau bug ne sont pas démontrées.
- Ancien planning effectivement fourni comme hint ; fixed_schedule=None. Horaires, affectations et groupes principaux libres sous les mêmes règles métier que l'essai depuis zéro. Une seule recherche automatique : 599,703 s, 3 891 conflits, 394 253 branches.
- Dix minutes entre sites conservées ; aucun assouplissement. Historique toujours invalide pour sept déplacements sans délai ; aucun planning actif remplacé.
- Empreintes des sources de production, données et configuration identiques avant/après. Aucun changement de production ni nouveau test de production ; dernier contrôle publié : 103 tests réussis.
- Résultats conservés dans docs/experiments/2026-10-18-guided-600s/README.md, summary.json et evidence.json (scripts, conditions, logs, résultat, contrôle de sortie et revalidation historique).
- Blocage : aucun premier candidat conforme trouvé, malgré les deux essais complets depuis zéro puis guidé. Prochaine piste : diagnostic ciblé des contraintes autour des remplacements/déplacements. Aucun nouveau calcul lancé après cet essai et aucune nouvelle règle décidée.


## Diagnostic ciblé autorisé — 19 octobre 2026

- Frédéric demande le diagnostic proposé pour éviter des relances longues sans hypothèse testable. Premier cas : remplacement de Fanny le lundi, aller-retour haut/bas.
- Hypothèse : deux interruptions de déplacement imposent au moins trois périodes de présence ; le modèle actuel autorise au plus deux périodes. Vérifier par cas isolés, contrôle sans trajet, contrôle avec un seul trajet et revalidation de la semaine historique.
- Code et données de production inchangés. Aucun calcul global ni assouplissement métier autorisé/décidé pour ce diagnostic. Résultats dans docs/experiments/2026-10-19-travel-diagnostic/.
- Aucun AGENTS.md ou MODEL_GUIDE.md trouvé dans les copies accessibles ; aucun outil Brain disponible identifié. OR-Tools absent de l'environnement courant ; réinstallation isolée en cours, sans modifier les dépendances du projet.
- Prochaine action : exécuter les comparaisons bornées et consigner les conclusions avec leurs limites.


## Diagnostic confirmé sur les déplacements — 19 octobre 2026

- Six cas comparatifs exécutés avec assertions, validateur de production et cinq résolutions CP-SAT courtes ; cas « trois périodes » refusé explicitement par le compact avant résolution. OR-Tools 9.15.6755 réinstallé dans un environnement isolé ; exécution finale du diagnostic en moins d'une seconde.
- Fanny lundi : haut → bas pour remplacer Trotteur 13:15–14:00 → haut. Deux délais de trajet créent trois périodes de présence, au-delà du maximum de deux. Le validateur ne remonte alors que cette erreur dans le cas réduit et le CP-SAT le déclare INFEASIBLE. Les témoins sans changement de site ou avec un seul trajet sont valides et OPTIMAL.
- Énumération indépendante de 126 755 intervalles/paires d'intervalles : aucune couverture des trois activités requises avec deux créneaux de trajet vides en au plus deux périodes. Preuve locale, pas une preuve d'infaisabilité globale.
- Ajout naïf des délais aux sept trajets de la semaine réelle : zéro erreur de déplacement, mais trois journées à trois périodes (A repourvoir mardi, Fanny lundi, Priscila mardi) et cinq créneaux en sous-effectif d'une personne : Grands lundi 13:00, Nurserie mardi 14:00, Trotteur mardi 13:00 et 14:15, Grands jeudi 13:00. Valérie jeudi passe à deux périodes.
- Le modèle compte actuellement le temps de trajet libre comme une interruption de présence. Ce choix explique le conflit local ; la façon métier de compter un déplacement dans une période de travail n'est pas redéfinie ici. Aucun nouveau bug démontré, aucune limite assouplie.
- Limites : mini-cas avec contrat adapté, sans THE, qualification ni besoins de couverture ; semaine réelle revalidée avec toutes ses règles. Aucun nouveau calcul global ni suite complète de tests exécutés. Sources de production, données et configuration inchangées, empreintes identiques à l'essai guidé précédent.
- Traces : docs/experiments/2026-10-19-travel-diagnostic/README.md, summary.json et evidence.json. Aucun planning actif remplacé.
- Prochaine hypothèse précise : réorganiser les remplacements et journées autour des cinq créneaux identifiés en conservant dix minutes de trajet et deux périodes ; ne plus tenter de garder les mêmes trois activités avec un aller-retour pour la même personne. La cause complète des résultats globaux UNKNOWN reste non établie.


## Décision et correction des interruptions de trajet — 19 octobre 2026

- Frédéric demande d'autoriser ce type d'interruption après le diagnostic. Interprétation appliquée : un trajet minimal nécessaire entre sites ne consomme pas une coupure classique ni une période supplémentaire ; une longue pause ou une interruption sur le même site conserve les règles existantes.
- Minimum de dix minutes conservé, arrondi à quinze minutes sur la grille actuelle. Validateur, comptage des périodes et automate CP-SAT harmonisés. Les patrons réservent les créneaux de déplacement dans leurs périodes ordinaires et savent conserver les journées fixées avec aller-retour.
- Les trajets ne couvrent ni enfants ni colloques, et aucun nouveau temps contractuel n'est ajouté. Calcul des heures et politique de score conservés. Le cas sans pause classique autorisée est aussi vérifié ; les vraies pauses restent limitées. Aucun passage général à trois périodes ordinaires.
- **117 tests réussis en 14,057 secondes**, dont quatorze nouveaux tests ciblés ; compilation et git diff --check réussis, Python 3.12 / OR-Tools 9.15.6755.
- Le cas isolé de l'aller-retour passe maintenant. Sur la semaine historique avec les sept délais insérés, les trois erreurs de périodes disparaissent ; restent cinq créneaux en sous-effectif : Grands lundi 13:00, Nurserie mardi 14:00, Trotteur mardi 13:00 et 14:15, Grands jeudi 13:00. Aucun planning complet nouvellement valide ni remplacement du planning actif.
- Sources modifiées : domain.py, solver.py, pattern_mip.py ; tests de régression et documentation métier/utilisateur ajoutés. Données et configuration inchangées. Résultats : docs/experiments/2026-10-19-travel-interruptions/.
- Limites : anciens refus explicites des patrons conservés ; pas de garantie d'équivalence exhaustive ni de mesure de performance sur la semaine réelle. Le diagnostic précédent reste une trace de l'ancienne règle.
- Prochaine action : rechercher une réorganisation autour des cinq créneaux en sous-effectif avec les interruptions de trajet désormais autorisées. Aucun nouveau calcul global lancé pendant cette correction.


## Seconde revue indépendante — 19 octobre 2026

### État vérifié
- Revue de `main` au commit `748acbb3a4c96250f8659bc7683a0222a78072f2`, incluant l'autorisation des interruptions minimales de trajet ; tête distante revérifiée avant publication.
- Lecture de l'état, des règles métier, du suivi des corrections et du dernier diff. Aucun AGENTS.md / MODEL_GUIDE.md trouvé dans le dépôt et les emplacements /workspace inspectés ; aucun outil Brain disponible identifié.
- **117 tests existants réussis en 13,369 s**. Diagnostics indépendants : **29 appels de micro-résolution**, environ 7,4 s au total, assertions du comportement observé réussies. Aucun calcul global long.

### Résultats confirmés et changements
- Rapport et preuves : `docs/audits/2026-10-19-second-review/README.md`, `probes.py`, `results.json`, journaux, empreintes et exports synthétiques.
- R1 : filtres/coûts horaires des patrons appliqués avant retrait des trajets. Un aller-retour respectant deux interdictions sur les créneaux vides passe le validateur, CP-SAT et les patrons fixés, mais est absent du domaine libre ; les préférences soft sur ces mêmes créneaux ajoutent aussi une pénalité sans présence.
- R2 : les patrons tronquent la fenêtre de remplacement au colloque strict. Un planning fixé voit 45 minutes de remplacement transférées à un autre groupe, avec status=ok si aucune demande discriminante ne l'interdit ; avec la couverture du témoin, faux échec des patrons alors que CP-SAT et validateur l'acceptent.
- R3 : le bilan qualité/HTML annonce deux violations de coupure pour deux trajets minimaux exemptés, malgré zéro erreur hard.
- R4 : le résumé des règles exporté annonce encore l'ancien quota d'une personne de chaque autre groupe, contrairement à la règle et aux moteurs corrigés.
- Aucun code de production, donnée métier, configuration ou planning actif modifié. Empreintes des sources/données/configuration/fixtures/sorties identiques avant et après les sondes.

### Contrôles, limites et prochaine action
- Contrat/THE non nul contrôlé : 2,5 h enfants + 0,75 h THE invisible = 3,25 h ; aucune heure de trajet ajoutée. Aucune couverture pendant les trajets. Score compact identique au recalcul ; pénalités soft des interruptions conservées intentionnellement.
- Aucun lien démontré entre ces défauts et les anciens UNKNOWN ; aucun nouveau planning complet conforme obtenu ou recherché. Limites explicites des patrons, Windows et interface restent distinctes des bugs. Pas de nouvelle décision métier prise.
- Prochaine action utile : corriger R1/R2 par les cas minimaux conservés, puis R3/R4 ; rejouer diagnostics et tests avant une nouvelle optimisation globale. Cette revue seule n'autorise ni n'applique ces corrections de production.


## Corrections de la seconde revue — 19 octobre 2026, en cours

- Autorisation : Frédéric demande de corriger les quatre constats, puis de continuer les corrections en cours. Base publiée : `3e17641d366321641be22ad968272a8e9e1ae198` ; branche locale isolée `fix/second-review-2026-10-19`.
- Douze tests de régression ajoutés avant modification : exécution en 5,435 s, onze assertions/sous-cas en échec reproduisant R1–R4 ; les témoins de protection restent distincts des bugs.
- Corrections en cours dans les patrons (contrôles horaires après réservation des trajets, créneaux explicites de remplacement et préservation des jours fixés), les métriques de coupures et le texte des règles exporté. Données métier, configuration et plannings inchangés.
- Aucun nouveau calcul global. Prochaine action : exécuter les régressions, traiter tout écart puis contrôler la suite complète avant publication. Les modifications ne sont pas encore déclarées validées.

### Contrôle intermédiaire des corrections

- Les cas principaux R1–R4 passent. Un témoin de remplacement partiel a révélé que `diagnose_the_capacity` conservait aussi l'ancien quota de remplaçants : il annonçait 1,50 h de besoin pour 1 h disponible alors que le validateur et CP-SAT acceptaient le témoin. Preuve conservée dans `corrections/capacity-before.json` ; le diagnostic utilise désormais les seuls besoins de couverture définis.
- Les journées fixées conservent leurs créneaux et activités, y compris plusieurs remplacements ; les dépassements de fenêtre sont refusés. Seize tests ciblés couvrent aussi les protections hard et les heures/THE.
- Un essai libre de contrôle comptable a atteint sa limite HiGHS avec 14 599 patrons : ce n'est pas une preuve de bug métier. Le test comptable est isolé à planning fixé ; la génération libre reste testée séparément. Déduplication renforcée des patrons produisant exactement les mêmes affectations après retrait des trajets, pour limiter la croissance du domaine.
- Prochaine action : contrôle final ciblé puis suite complète. Aucun calcul global lancé.

### Corrections de la seconde revue validées — 19 octobre 2026

- **133 tests réussis en 31,546 s**, dont seize nouveaux tests dans `tests/test_second_review_regressions.py`. Compilation réussie et contrôle Git du code/documentation sans erreur d'espaces.
- R1 corrigé : règles horaires et préférences évaluées sur la présence après retrait des trajets ; préfiltrage conservateur. R2 corrigé : marges et remplacements partiels représentés, journées fixées préservées créneau par créneau, dépassement de fenêtre refusé. Les patrons de même affectation finale sont dédupliqués.
- R3 corrigé : trajets minimaux séparés des coupures classiques dans les métriques/exports. R4 corrigé : texte des règles sans ancien quota ; son résidu dans `diagnose_the_capacity`, découvert par le test partiel, est également supprimé et couvert par un témoin valide et un vrai déficit de capacité.
- Sources modifiées : `pattern_mip.py`, `quality.py`, `reports.py` et le seul diagnostic de capacité dans `solver.py`. Objectif compact et `scoring.py` inchangés. Données, configuration, fixtures et sorties actives identiques par empreintes.
- Dossier de preuve : `docs/audits/2026-10-19-second-review/corrections/README.md`, tests avant/après, témoin du résidu de quota, validation et exports synthétiques. Le journal intermédiaire conserve le seul écart de message de refus, résolu ; les traces d'audit initiales restent historiques.
- Aucun calcul global, aucun nouveau planning complet déclaré conforme. Limites conservées : domaine des patrons libres, options explicitement non supportées, absence de test Windows/graphique et de mesure de performance globale. Prochaine action utile : reprise ciblée des cinq créneaux de couverture si elle est demandée.


## Relance depuis zéro après corrections — 19 octobre 2026

- Relance CP-SAT compacte demandée et exécutée sur la version corrigée pendant **600,435 secondes**, de 12:11:19 à 12:21:20 UTC. Aucun ancien planning fourni comme hint, aucun planning fixé, aucune modification des contraintes en cours d'exécution.
- Processus terminé normalement avec code de sortie **0**. Statut final **UNKNOWN**, zéro solution et aucun checkpoint. Ce résultat ne démontre ni l'infaisabilité globale, ni un nouveau bug.
- Modèle : 35 711 variables et 82 398 contraintes. Six hypothèses internes de groupes : trois `INFEASIBLE`, trois `UNKNOWN`. Recherche automatique : 360,299 s, 700 387 conflits et 2 059 553 branches. Portfolio : 148,670 s, 207 conflits et 39 629 branches.
- Aucun planning à revalider ou sélectionner. Aucun planning actif remplacé. Les sources de production, données, configuration et sorties actives ont des empreintes identiques avant/après.
- Preuves : `docs/experiments/2026-10-19-from-zero-600s-after-review/README.md`, `conditions.json`, `run.log`, `cp_sat.log`, `result.json`, `summary.json`, `integrity.json`, `process_status.json` et `evidence.json`.
- Dernière validation fonctionnelle inchangée : **133 tests réussis en 31,546 s** avant cette relance. Prochaine action utile : diagnostic court ou recherche guidée autour des cinq créneaux de couverture déjà isolés ; une relance strictement identique a peu de valeur informative.


## Réparation locale des cinq créneaux — 19 octobre 2026

- Diagnostic court exécuté à la demande de Frédéric, sans recherche globale. Le témoin avec délais de trajet reproduit exactement les cinq déficits connus puis une réorganisation de huit bornes horaires les supprime tous.
- **Planning complet valide trouvé** : validateur `ok`, zéro erreur hard et zéro erreur de déplacement. CP-SAT fixé : `OPTIMAL` en 1,270 s. Patrons fixés : `Optimal` en 0,047 s. Les affectations par créneau sont identiques dans les trois contrôles.
- Changements : X lundi +15 min ; mardi Natacha déplace 15 min de 11:30–11:45 vers 13:00–13:15, « A repourvoir » reprend 11:30–11:45, Emilie et Léa prolongent chacune de 15 min ; jeudi Tara déplace 15 min de 07:45–08:00 vers 13:00–13:15.
- Score commun recalculé : **743 872** pour le candidat, CP-SAT et les patrons. Exports CSV/HTML générés ; l'HTML annonce les règles hard OK et exclut correctement les trajets minimaux des coupures classiques.
- Aucun bug nouveau démontré. Aucun code de production, donnée, configuration ou planning actif modifié ; empreintes identiques avant/après. Le candidat reste uniquement dans `docs/experiments/2026-10-19-five-slot-local-repair/`.
- Limite : témoin de faisabilité locale, sans garantie que la recherche libre le retrouve. Prochaine décision utile : conserver ce candidat comme preuve seulement ou l'utiliser comme hint d'une optimisation courte ; aucune activation de planning n'est faite ici.


## Maximum hard de coupure fixé à 90 minutes — 19 octobre 2026

- Frédéric confirme qu'une coupure de 90 minutes est acceptable mais qu'une coupure de trois heures ne l'est pas. La limite devient une règle hard : `max_pause_between_blocks_minutes=90` et `enforce_max_pause_between_blocks=true`, dans la configuration du projet et ses valeurs par défaut.
- Le candidat de réparation locale précédent est désormais explicitement historique et invalide sous cette règle : Léa a une coupure de 180 minutes le jeudi, de 10:00 à 13:00. Sa documentation porte un avertissement ; aucun planning actif n'avait été remplacé.
- Documentation métier et utilisateur alignée. Un test vérifie la valeur et son activation dans les valeurs par défaut comme dans `config/solveur_config.json`.
- Réparation complète construite sans assouplissement : Tara, Léa, Céline et Emilie ont des coupures de 90 minutes au maximum ; l'horaire de Fanny jeudi est décalé pour préserver la couverture.
- Résultat exécuté : validateur `ok`, aucune erreur hard ni de déplacement ; CP-SAT fixé `OPTIMAL` en 1,092 s et patrons fixés `Optimal` en 0,022 s, mêmes affectations et score commun 760979.
- Suite complète après activation de la règle : **134 tests réussis en 31,396 s**.
- Preuves : `docs/experiments/2026-10-19-hard-90-minute-repair/README.md`, candidat JSON/CSV/HTML, sorties des deux moteurs, synthèse, empreintes et script reproductible. Aucun planning actif remplacé.
- Limite : la faisabilité du candidat fixé est démontrée, pas sa redécouverte ni son optimalité en recherche libre. Les recherches courtes arrivées à leur limite restent `UNKNOWN`/sans solution primale et ne prouvent pas l'infaisabilité.
- Prochaine action utile : décider explicitement si ce candidat doit rester une preuve ou devenir la nouvelle référence/hint ; aucune activation n'est faite ici.


## Recherche guidée de coupures plus courtes — 20 octobre 2026

- Recherche CP-SAT guidée demandée par Frédéric, budget 120 secondes, depuis le candidat valide sous maximum hard de 90 minutes. Horaires et affectations libres ; aucun planning fixé et aucun assouplissement.
- Résultat `FEASIBLE` : toujours huit journées coupées, mais durée totale réduite de **11 h à 8 h 45**, soit 2 h 15 de moins. Coupure maximale inchangée à 90 minutes. Score commun 760979 → 702701.
- Réductions : Tara jeudi 90→75 min, Léa jeudi 90→15 min, Emilie vendredi 90→60 min, Priscila mardi 75→60 min. Les quatre autres coupures gardent leur durée.
- Validateur : zéro erreur hard et de déplacement. Patrons fixés : `Optimal` en 0,013 s, mêmes affectations par créneau et même score. Empreintes des sources, données, configuration et sorties actives inchangées.
- Preuves : `docs/experiments/2026-10-20-guided-fewer-breaks-120s/README.md`, synthèse, journaux, résultat JSON/CSV/HTML, contrôle croisé et scripts reproductibles. Aucun planning actif remplacé.
- Limite : aucun optimum prouvé. Ne pas interpréter l'absence de résultat sous huit journées coupées pendant 120 secondes comme une impossibilité. Le candidat améliore la durée totale mais modifie de nombreuses journées.
- Prochaine action utile : examiner visuellement ce candidat avant toute adoption ; si la priorité absolue est de descendre sous huit journées coupées, lancer ensuite une recherche dédiée avec cette borne comme hypothèse testable.

## Horaires individuels dans le rapport — 20 octobre 2026

- Demande de Frédéric : ajouter les horaires hebdomadaires par personne au résultat, en complément du planning par groupe, puis publier le commit.
- Base inspectée : `0aca2b1` sur `main`. État du projet et règles métier lus ; aucun AGENTS.md ni MODEL_GUIDE.md trouvé dans le dépôt ou les emplacements /workspace inspectés ; aucun outil Brain disponible identifié.
- Générateur `reports.write_html` complété : navigation entre les vues, fiche de cinq jours par personne, plages triées avec site/groupe/activité, jours libres, heures visibles et totaux hebdomadaires existants. Le THE hors colloque reste explicitement non planifié.
- Dernier résultat guidé régénéré dans `docs/experiments/2026-10-20-guided-fewer-breaks-120s/result.html` ; empreinte HTML actualisée. Aucun nouveau calcul, aucune modification des données JSON/CSV, du candidat, des règles ou du solveur.
- Contrôle structurel de l'export : 13 personnes, 65 journées, 79 plages, correspondance exacte au JSON ; tri, échappement HTML, jours libres, calcul des heures visibles et absence de mutation du payload vérifiés. Suite complète : **134 tests réussis en 29,365 s** ; `git diff --check` réussi. Aucun contrôle visuel dans un navigateur ni test réel sous Windows effectué.
- Prochaine action : publier et vérifier le commit distant, puis ouvrir la section Horaires individuels pour la revue utilisateur. Aucun blocage identifié à ce stade.


## Essai depuis zéro sous maximum de 90 minutes — 20 octobre 2026

- Frédéric demande de mettre le programme à l’épreuve depuis zéro. Essai CP-SAT compact borné à 600 secondes sur `deab5fa`, sans planning fourni, sans hint et sans affectations fixées. Les hypothèses internes de groupes et stratégies automatiques du moteur restent actives.
- Même protocole que la relance précédente depuis zéro, avec la règle hard actuelle de coupure maximale de 90 minutes. Les options et empreintes sont enregistrées dans `docs/experiments/2026-10-20-from-zero-600s-hard-90/conditions.json`. Aucune règle assouplie, aucun ancien résultat utilisé comme secours dans cet essai.
- Dernière suite existante : 134 tests réussis en 29,365 s avant cet essai. Données, configuration et code de production inchangés. Tout candidat trouvé sera revalidé et exporté avec les horaires individuels ; les sorties actives restent protégées.
- Résultat vérifié : **600,216 secondes**, de 07 h 10 min 15 s à 07 h 20 min 15 s, heure suisse. Fin normale, code de sortie **0** ; statut **UNKNOWN**, zéro solution et aucun checkpoint. Aucun planning à revalider, aucune optimisation commencée.
- Six hypothèses internes : trois INFEASIBLE localement et trois UNKNOWN. Recherche générale automatique : 360,185 s, 768 conflits, 189 273 branches ; portfolio : 148,444 s, 1 857 conflits, 328 254 branches. Aucune preuve d’infaisabilité globale ni nouveau bug démontré.
- Intégrité avant/après vérifiée : données, configuration, code de production et sorties actives inchangés. Les exports de cet essai signalent l’absence de planning ; aucun candidat antérieur présenté comme résultat. Le rapport individuel publié dans `deab5fa` reste disponible sur le résultat guidé précédent.
- Preuves complètes et empreintes dans le dossier de l’essai ; aucune nouvelle suite de tests nécessaire au seul calcul, dernières 134 réussites inchangées. Limite explicite : essai CP-SAT compact, pas de l’orchestrateur `pattern_mip` ni de l’interface Windows.
- Prochaine piste utile, si demandée : diagnostic de la recherche initiale ou comparaison bornée des moteurs avec un protocole explicite. Pas de relance automatique identique après cet essai.


## Revue des techniques établies — 20 octobre 2026

- Frédéric demande d’examiner les techniques déjà implémentées et de choisir une méthode de référence publiée avant une adaptation. Base inspectée : `23da73d` ; copie de travail isolée `audit/known-methods-2026-10-20`. État et règles métier relus ; aucun AGENTS.md / MODEL_GUIDE.md trouvé dans le dépôt inspecté, aucun outil Brain disponible identifié.
- Le compact possède déjà deux phases, des hints, des hypothèses de groupes et plusieurs stratégies de faisabilité. Les patrons proposent un élargissement du domaine puis une amélioration ; le diagnostic de jours assouplis est marqué invalide. Ces mécanismes ne constituent pas une phase élastique de réparation chiffrée.
- Quatre micro-résolutions terminées avec assertions : planning fixé complet valide ; fixation partielle interprétée comme totale par le compact et donc infaisable sur le témoin ; désactivation hebdomadaire donnant un diagnostic invalide sans réparation ; hint invalide complété par le modèle strict sur ce seul cas facile. Aucun résultat global de performance déduit.
- Douze tests existants ciblés réussis (4 orchestration, 8 recherche par patrons). Sources, données, configuration et sorties protégées inchangées par empreintes. Aucun calcul global lancé, aucune implémentation de production.
- Méthode retenue pour le premier prototype à évaluer : **phase de faisabilité élastique L1 sur les minimums de couverture, puis optimisation stricte de la qualité**, référence concrète `workforce4` de Gurobi. Principe transposable à CP-SAT, sans nouvelle dépendance. Choix technique pour un essai, pas gain démontré ni modification des exigences finales.
- Le déficit provisoire serait explicite et minimisé ; les autres contraintes resteraient strictes. Seuls un déficit nul et la revalidation stricte autoriseraient un résultat utilisable. LNS métier différée après la construction initiale si les mesures la justifient ; les mécanismes internes de CP-SAT restent distincts.
- Comparaison, sources primaires, quatre sondes reproductibles, résultats et douze tests ciblés conservés dans `docs/audits/2026-10-20-known-methods/`. `git diff --check` réussi, aucune source de production modifiée, aucune nouvelle exécution globale.
- Prochaine étape concrète : implémenter ce prototype expérimental désactivé par défaut, tester l’équivalence à déficit nul et les protections hard, puis comparer au compact actuel à budget égal sans ancien planning. L’implémentation et le benchmark n’ont pas été exécutés dans cette revue.
