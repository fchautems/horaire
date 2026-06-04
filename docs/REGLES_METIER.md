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

   Une obligation de groupe `hard` impose le groupe principal indique. Une interdiction de groupe `hard` interdit ce groupe principal.

5. Maximum journalier

   Une personne ne doit pas depasser `rules_global.max_daily_hours` par jour.

6. Maximum hebdomadaire absolu

   Une personne ne doit jamais depasser `absolute_max_weekly_hours`, actuellement `40h`.

7. Heures contractuelles

   Le total hebdomadaire doit rester autour du taux contractuel, avec la tolerance configuree par `weekly_hours_tolerance_percent` et `weekly_hours_tolerance_step_minutes`. Ce total inclut le temps enfants et le THE.

8. Temps hors enfants (THE)

   Chaque educateur a `the_percent` de son temps contractuel en THE, actuellement `10%`. Les colloques font partie du THE. Le THE hors colloque est invisible dans le planning et ne compte pas dans la couverture enfants.

9. Minimum de journee

   Si une personne travaille un jour, elle doit faire au moins `min_daily_hours`, pour eviter les mini-presences.

10. Stabilite par demi-journee

   Une personne ne doit pas changer de groupe dans une meme demi-journee. Les remplacements de colloque sont l'exception.

11. Changements de groupe dans la semaine

   Une personne ne peut avoir qu'un nombre limite de jours avec changement de groupe, configure par `max_weekly_group_exception_days`.

12. Coupures

   Si une journee est coupee, la coupure ne doit pas depasser `smooth_max_split_gap_minutes`, actuellement `90 minutes`.

13. Groupes principaux et colloques

   Chaque educateur a un groupe principal. Le jour du colloque de ce groupe, il doit travailler dans ce groupe et participer au colloque complet. Le colloque compte comme THE et ne compte pas comme couverture enfants.

14. Remplacements de colloque

   Pendant un colloque, les personnes du groupe concerne ne couvrent plus les enfants. Une personne de chaque autre groupe vient remplacer. Ces remplacements ne comptent pas comme changements de groupe, mais comptent bien pour la couverture et les pourcentages du site.

## Regles soft

Ces regles guident le solveur, mais peuvent etre enfreintes si c'est necessaire pour respecter les regles hard.

1. Eviter les horaires coupes.
2. Garder les personnes dans le meme groupe sur la semaine.
3. Regrouper les temps partiels sur le moins de jours possible.
4. Respecter les preferences horaires et de groupe marquees `soft`.
5. Eviter les changements de site.
6. Eviter de faire venir une personne uniquement pour un colloque de 45 minutes.
