# Decisions validees

## Contraintes hard

- Granularite du planning : 15 minutes.
- Maximum hebdomadaire absolu : 40 heures.
- Heures contractuelles : tolerance maximale de plus ou moins 5 %, avec arrondi au pas configure.
- Disponibilites et regles horaires marquees `hard` obligatoires.
- Besoins minimums par groupe et par jour obligatoires.
- Maximum journalier obligatoire.
- Nombre maximal de jours travaille selon le pourcentage obligatoire.
- Un changement de site est autorise entre deux blocs d'une journee coupee.
- Aucun changement de groupe ordinaire au sein d'une meme demi-journee.
- Un remplacement de colloque peut exceptionnellement changer de groupe et de site.
- Maximum une journee ordinaire avec changement de groupe dans la semaine.
- Les pourcentages EDE/ASE/APE par site restent obligatoires, y compris pendant les colloques.
- Les controles finaux doivent confirmer toutes les contraintes hard.

## Contrat, THE et colloques

- Temps contractuel = temps enfants + THE.
- THE cible : 10 % du temps contractuel.
- THE ordinaire invisible dans le planning.
- Le colloque est du THE visible et dure 45 minutes.
- Une personne avec `attends_colloque: false` garde son THE mais n'a pas de colloque obligatoire.
- Le groupe principal determine le colloque obligatoire des personnes qui y participent.
- Le jour du colloque, un participant travaille dans son groupe principal et assiste au colloque complet.
- Pendant le colloque, la personne ne couvre pas les enfants.
- Un remplacement de colloque est exceptionnel et ne compte pas comme changement ordinaire de groupe.
- Un remplacement n'est cree que pour la couverture enfants effectivement perdue.

## Qualite soft

- Eviter les coupures et penaliser leur duree ; ne pas les interdire globalement.
- Les essais rapides peuvent limiter temporairement les coupures ou la grille horaire, mais la progression doit conserver un repli vers l'espace complet.
- Eviter les journees tres courtes par une penalite, pas une interdiction.
- Eviter les changements de groupe sur la semaine.
- Favoriser le groupe principal.
- Respecter autant que possible les preferences horaires et de groupe `soft`.
- Condenser fortement les temps partiels sur le minimum de jours ; la limite calculee de jours reste hard.

## Choix techniques

- Moteur de production actuel : `pattern_mip` avec SciPy/HiGHS.
- Recherche en deux objectifs conceptuels : trouver un planning hard-valide, puis ameliorer les criteres soft.
- Les coupures doivent rester presentes dans l'espace de recherche : le modele continu uniquement a deja ete prouve infaisable.
- `Time limit reached` signifie recherche inachevee ; seul `Infeasible` prouve l'impossibilite du modele execute.
- Le nombre de patrons ne depend pas du timeout.
- `fix_primary_groups_from_latest: true` reutilise les groupes principaux du dernier planning pour reduire les duplications. Les jours, horaires, groupes couverts, coupures et remplacements restent optimises.
- Les regles groupe `hard` ont priorite sur le groupe repris du dernier planning.
- La matrice et les index du moteur de patrons utilisent des tableaux compacts et un CSR direct.
- Les moteurs historiques restent dans `solver.py`, mais ne doivent pas remplacer `pattern_mip` sans audit d'equivalence metier.
- Un moteur historique peut produire un candidat uniquement si le validateur complet actuel decide ensuite de sa validite.
- Compatibilite des anciens JSON a conserver ; un enregistrement par l'editeur peut les normaliser vers le format actuel.
- Les sorties de calcul sont horodatees.
- `pattern_mip` est extrait dans un module separe, avec l'interface publique conservee dans `solver.py`.
