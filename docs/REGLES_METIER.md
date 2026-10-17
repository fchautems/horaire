# Regles metier du planning

Ce document sert de reference lisible pour le metier. Les valeurs qui peuvent changer sont dans `config/solveur_config.json` ou dans `data/gwendo.json`; ce fichier explique leur sens.

## Regles hard

Un planning marque `OK` doit respecter toutes ces regles.

1. Besoins minimums

   Chaque groupe doit avoir au moins le nombre de personnes demande dans `rules_site_schedule`, sur chaque tranche horaire.

2. Pourcentages de qualification par site

   Les proportions `EDE`, `ASE` et `APE` definies dans `rules_percentage` doivent etre respectees sur chaque site.

3. Regles horaires hard

   Une interdiction horaire `hard` interdit toute presence sur la plage. Une obligation horaire `hard` impose une presence sur la plage.

4. Regles de groupe hard

   Une obligation de groupe `hard` impose le groupe principal indique.
   Clarification du 17 octobre 2026 : une interdiction de groupe `hard` bloque les affectations ordinaires dans le groupe interdit, meme pour une journee entiere. Elle ne se limite pas au choix du groupe principal. Une preference negative `soft` penalise ces affectations sans les interdire. L'articulation avec les remplacements de colloque reste a preciser ; aucune nouvelle exception n'est decidee ici.

5. Maximum journalier

   Une personne ne doit pas depasser `rules_global.max_daily_hours` par jour.

6. Maximum hebdomadaire absolu

   Une personne ne doit jamais depasser `absolute_max_weekly_hours`, actuellement `40h`.

7. Heures contractuelles

   Le total hebdomadaire doit rester autour du taux contractuel, avec la tolerance configuree par `weekly_hours_tolerance_percent` et `weekly_hours_tolerance_step_minutes`. Ce total inclut le temps enfants et le THE.

8. Temps hors enfants (THE)

   Chaque educateur a `the_percent` de son temps contractuel en THE, actuellement `10%`. Les colloques font partie du THE. Le THE hors colloque est invisible dans le planning et ne compte pas dans la couverture enfants.

9. Stabilite par demi-journee

   Une personne ne doit pas changer de groupe dans une meme demi-journee. Les remplacements de colloque sont l'exception.

10. Changements de groupe dans la semaine

   Une personne ne peut avoir qu'un nombre limite de jours avec changement de groupe en cours de journee, configure par `max_weekly_group_exception_days`.
   Clarification du 17 octobre 2026 : travailler toute une journee dans un autre groupe que son groupe principal ne constitue pas, a lui seul, un jour avec changement de groupe. Cette affectation reste possible si aucune regle hard ne s'y oppose, avec les penalites soft applicables et dans le respect des autres contraintes, notamment des colloques.
   Si un changement dans la journee est necessaire, une matinee dans un groupe puis un apres-midi dans un autre est possible ; les changements au sein d'une demi-journee restent interdits hors exception de remplacement de colloque.
   Les personnes marquees comme ne participant pas aux colloques peuvent etre utilisees plus souplement.

11. Groupes principaux et colloques

   Chaque educateur a un groupe principal. Le jour du colloque de ce groupe, il doit travailler dans ce groupe et participer au colloque complet. Le colloque compte comme THE et ne compte pas comme couverture enfants.
   Une personne peut etre marquee comme ne participant pas aux colloques; dans ce cas elle garde son THE, mais n'a pas de colloque visible obligatoire.

12. Remplacements de colloque

   Pendant un colloque, les personnes du groupe concerne ne couvrent plus les enfants. Une personne de chaque autre groupe vient remplacer. Ces remplacements ne comptent pas comme changements de groupe, mais comptent bien pour la couverture et les pourcentages du site.

## Regles soft

Ces regles guident le solveur, mais peuvent etre enfreintes si c'est necessaire pour respecter les regles hard.

1. Eviter les horaires coupes.
2. Si une coupure est necessaire, la garder aussi courte que possible; `max_pause_between_blocks_minutes` sert de seuil de reference.
3. Eviter les journees de moins de `min_daily_hours`, actuellement `2 heures`, sans les interdire.
4. Garder les personnes dans le meme groupe sur la semaine.
5. Regrouper les temps partiels sur le moins de jours possible.
6. Respecter les preferences horaires et de groupe marquees `soft`.
7. Eviter les changements de site.
8. Eviter de faire venir une personne uniquement pour un colloque de 45 minutes.

## Etat d'application — 17 octobre 2026

Les clarifications ci-dessus expriment les regles metier confirmees par Frederic. La limite hebdomadaire du moteur compact CP-SAT est maintenant alignee : seules les journees avec changement de groupe en cours de journee consomment la limite. Une journee entiere hors groupe principal reste possible, avec les penalites soft existantes et les autres contraintes applicables.

Les interdictions hard de groupe ne portent encore que sur le groupe principal dans le code : leur application aux affectations ordinaires reste a corriger. L'articulation avec les remplacements de colloque reste a preciser. Voir `PROJECT_STATE.md` pour les controles, limites et prochaines actions.
