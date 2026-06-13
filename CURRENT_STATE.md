# Etat actuel du projet

Date de reference : 13 juin 2026.

## But

Generer un planning hebdomadaire de creche a partir de `data/gwendo.json`, avec controle des contraintes hard, optimisation des preferences soft, export JSON/CSV/HTML et edition graphique.

## Etat fonctionnel

- L'editeur ouvre, modifie, valide et enregistre le JSON.
- L'editeur peut lancer le solveur et afficher sa progression.
- Le staffing accepte des besoins differents selon les jours.
- Les sorties sont horodatees et un dernier planning valide peut etre recharge.
- Les exports texte, CSV et HTML existent.
- Le moteur actif est `pattern_mip`.
- Le dernier commit pousse est `092407e` sur `main`.
- Les modifications de stabilisation actuelles sont presentes dans le repertoire de travail, mais ne sont pas encore commitees.

## Etat du solveur

Le solveur a ete stabilise et separe :

- `solver.py` conserve l'orchestration et l'interface publique ;
- `pattern_mip.py` contient la generation des patrons, la matrice et l'appel HiGHS ;
- `pattern_search.py` contient les essais progressifs, budgets et choix du candidat ;
- la recherche vise d'abord un candidat hard-valide, puis une amelioration soft ;
- le dernier planning valide n'est remplace que si les controles finaux sont sans erreur ;
- l'interface affiche l'etape et son budget, et arrete l'arbre de processus sous Windows ;
- 23 tests de regression passent.

La recherche par patrons a aussi ete rendue progressive :

- les deux premieres tentatives utilisent uniquement des journees continues, avec changement de groupe entre demi-journees autorise ;
- les coupures sont ajoutees ensuite, puis l'espace complet en dernier recours ;
- les patrons dont les heures ne peuvent mathematiquement pas completer la semaine sont retires ;
- les regles horaires sont pre-calculees par masques et les couts repetes sont mis en cache ;
- une reserve de temps empeche de transmettre un tres gros modele a HiGHS lorsqu'il ne reste pas assez de budget pour son chargement natif.

La memoire du moteur a ete reduite :

- suppression de la table geante de signatures de patrons ;
- metadonnees de patrons stockees dans des tableaux compacts ;
- index de couverture et de matrice stockes dans des tableaux d'entiers ;
- construction CSR sans grandes listes temporaires ;
- expiration controlee pendant la generation.

Le test utilisateur de 2 000 secondes du 12 juin a genere 935 658 patrons, puis `python.exe` a subi un `APPCRASH`. Ce resultat ne prouvait aucune infaisabilite. Apres compactage, les sous-modeles de 150 000 a environ 330 000 patrons terminent sans crash et donnent un statut HiGHS exploitable.

Le 13 juin, un benchmark limite a 180 secondes a termine proprement en environ 170 secondes :

- 53 729 patrons continus guides : `Infeasible` ;
- 59 564 patrons continus libres : `Infeasible` ;
- 717 582 patrons avec coupures : non lance dans HiGHS faute de budget de chargement suffisant ;
- 1 356 055 patrons complets : timeout pendant la construction du modele.

Un calcul reel de 2 000 secondes a ensuite ete execute :

- 53 523 patrons continus guides : `Infeasible` ;
- 59 564 patrons continus libres : `Infeasible` ;
- 715 311 patrons avec coupures : aucun candidat trouve dans le budget ;
- 1 356 055 patrons complets : aucun resultat avant la limite globale.

Le processus direct a ete arrete apres depassement de la limite dans l'appel natif HiGHS. Aucun fichier de sortie valide n'a ete remplace.

## Resultats etablis

- Le planning assoupli du 11 juin est reproductible exactement avec 65 patrons et `checks.errors == []` lorsque la limite de jours est desactivee.
- La conversion de ce planning en patrons fixes est donc valide.
- Plusieurs espaces reduits ont ete prouves `Infeasible`, notamment les grilles 60 minutes, les grilles mixtes 60/30 minutes, les coupures jusqu'a 90 minutes et plusieurs reparations locales.
- Une optimisation locale assouplie optimale ramene Valerie a 3 jours.
- Le blocage minimal observe reste :
  - `A repourvoir` : 5 jours pour un maximum de 4 ;
  - `Natacha` : 4 jours pour un maximum de 3 ;
  - `Anais` : 5 jours pour un maximum de 3.
- Aucun planning strictement valide n'est encore confirme.
- Les modeles sans coupure sont maintenant prouves infaisables avec les regles courantes.
- Les modeles avec coupures restent trop grands pour constituer une voie de recherche efficace sous leur forme exhaustive actuelle.
- Ces preuves concernent les sous-modeles executes. Elles ne prouvent pas encore l'infaisabilite du modele metier complet a 15 minutes.

`outputs/planning_gwendo_latest.json` est ancien. Il porte `status: ok`, mais provient d'une execution avec limite de jours assouplie. Il peut guider une reparation, mais ne doit pas etre presente comme planning strictement valide.

## Configuration actuelle

Fichier : `config/solveur_config.json`.

Valeurs importantes :

- `solver_engine`: `pattern_mip`;
- `time_limit_seconds`: `2000`;
- `weekly_hours_tolerance_percent`: `5.0`;
- `absolute_max_weekly_hours`: `40`;
- `hard_max_work_days`: `true`;
- `max_pause_between_blocks_minutes`: `120`;
- `enforce_max_pause_between_blocks`: `false`;
- `fix_primary_groups_from_latest`: `true`;
- `restricted_patterns`: `false`;
- granularite : 15 minutes.

## Fichiers importants

- `data/gwendo.json` : donnees metier, educateurs et regles.
- `config/solveur_config.json` : parametres du calcul et des sorties.
- `src/creche_planning/solver.py` : orchestration et moteurs, dont `pattern_mip`.
- `src/creche_planning/pattern_mip.py` : generation compacte des patrons, matrice CSR et appel HiGHS.
- `src/creche_planning/pattern_search.py` : progression des essais, budgets et conservation du candidat valide.
- `src/creche_planning/domain.py` : temps, jours, staffing, colloques, THE et tolerances.
- `src/creche_planning/editor.py` : interface graphique et validation des donnees.
- `src/creche_planning/reports.py` : rapport console, CSV et HTML.
- `src/creche_planning/quality.py` : profils et metriques de qualite.
- `src/creche_planning/runtime.py` : configuration, chemins et progression.
- `solveur_v2.py` : lanceur compatible du solveur.
- `creche_editor.py` : lanceur compatible de l'editeur.
- `lancer_solveur.bat` / `lancer_editeur.bat` : lancement Windows.
- `docs/REGLES_METIER.md` : formulation metier des contraintes.
- `docs/DOCUMENTATION_UTILISATEUR.md` : parametres et utilisation.
- `docs/ETAT_REPRISE_SOLVEUR.md` : historique technique des derniers diagnostics.

## Etat du repertoire

Le repertoire de travail contient des modifications de code et des tests non commites. Les fichiers de reprise Markdown sont egalement non suivis par Git. Ne pas ajouter les captures ou fichiers temporaires sans demande.
