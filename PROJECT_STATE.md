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
