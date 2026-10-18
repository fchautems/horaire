# Regles metier du planning

Ce document sert de reference lisible pour le metier. Les valeurs qui peuvent changer sont dans `config/solveur_config.json` ou dans `data/gwendo.json`; ce fichier explique leur sens.

## Regles hard

Un planning marque `OK` doit respecter toutes ces regles.

1. Besoins minimums

   Chaque groupe doit avoir au moins le nombre de personnes demande dans `rules_site_schedule`, sur chaque tranche horaire.

2. Pourcentages de qualification par site

   Les proportions `EDE`, `ASE` et `APE` definies dans `rules_percentage` doivent etre respectees sur chaque site sur les heures enfants cumulees de la semaine (confirmation du 18 octobre 2026), et non a chaque instant.

3. Regles horaires hard

   Une interdiction horaire `hard` interdit toute presence sur la plage. Une obligation horaire `hard` impose une presence sur la plage.

4. Regles de groupe hard

   Une obligation de groupe `hard` impose le groupe principal indique.
   Clarification du 17 octobre 2026 : une interdiction de groupe `hard` bloque les affectations ordinaires dans le groupe interdit, meme pour une journee entiere. Elle ne se limite pas au choix du groupe principal. Une preference negative `soft` penalise ces affectations sans les interdire. Confirmation du 18 octobre 2026 : les interdictions de groupe ne s'appliquent pas pendant un remplacement de colloque authentifie.

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

   Pendant un colloque, les personnes du groupe concerne ne couvrent plus les enfants. Les remplacements sont determines par la couverture enfants effectivement perdue ; il n'y a pas de quota automatique d'une personne de chaque autre groupe. Ces remplacements ne comptent pas comme changements de groupe, mais comptent bien pour la couverture et les pourcentages du site.

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

## Etat d'application — 18 octobre 2026

Les clarifications ci-dessus expriment les regles metier confirmees par Frederic. La limite hebdomadaire du moteur compact CP-SAT est maintenant alignee : seules les journees avec changement de groupe en cours de journee consomment la limite. Une journee entiere hors groupe principal reste possible, avec les penalites soft existantes et les autres contraintes applicables.

Les interdictions hard de groupe sont appliquees aux affectations ordinaires dans le moteur compact, le moteur par patrons et le validateur. L'exception pendant un remplacement de colloque authentifie est confirmee le 18 octobre 2026. Voir `PROJECT_STATE.md` pour les controles, limites et prochaines actions.


## Présence avant l'ouverture et après la fermeture — décision du 18 octobre 2026

Frédéric confirme qu'une éducatrice peut travailler sur un site avant l'ouverture ou après la fermeture, notamment pour préparer l'accueil ou ranger. Les heures d'ouverture et de fermeture du site ne constituent donc pas, à elles seules, une interdiction hard de présence. Les autres contraintes du planning restent applicables.


## Précisions métier du 18 octobre 2026 — qualifications, remplacements et déplacements

- Qualifications : calcul des proportions par site sur les heures enfants cumulées de la semaine.
- Remplacements de colloque : fenêtre autorisée de quinze minutes avant et trente minutes après ; toute personne peut remplacer, sans condition de groupe d'origine, sous réserve des autres contraintes de présence et de contrat. Les interdictions de groupe ne s'appliquent pas à ces remplacements authentifiés ; elles restent obligatoires pour les affectations ordinaires.
- Repos entre deux journées : aucun minimum interjournalier demandé dans le modèle. Cette précision ne définit pas les pauses au sein d'une journée.
- Déplacements entre sites : prévoir au moins dix minutes entre deux affectations sur des sites différents. Cette nouvelle contrainte est à implémenter et les plannings doivent ensuite être revalidés. La grille actuelle de quinze minutes ne doit pas conduire à réduire silencieusement ce délai.
- Le sens d'une obligation horaire positive reste à préciser : présence pendant toute la fenêtre ou présence partielle dans cette fenêtre. Aucun changement de ce comportement avant clarification.
