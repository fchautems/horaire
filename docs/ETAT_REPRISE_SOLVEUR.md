# Etat de reprise du solveur

Date : 7 juin 2026

## Derniere livraison

- Branche : `codex/fix-quarter-hour-patterns`
- Commit pousse : `faa225f`
- Compilation et controles cibles : OK

Cette livraison :

- corrige le plantage `tolerance_slots` du chemin CP-SAT ;
- affiche le nombre de patrons continus, coupes, mixtes et avec remplacement ;
- explique dans la documentation que le nombre de patrons ne depend pas du timeout ;
- distingue `Time limit reached` (recherche inachevee) de `Infeasible` (modele prouve impossible).

## Probleme encore ouvert

Le moteur `pattern_mip` genere environ 1,6 million de patrons avec la configuration complete. Ce nombre correspond a des journees candidates, pas a 1,6 million de plannings hebdomadaires. Le solveur doit ensuite combiner ces candidats entre toutes les personnes et tous les jours.

Augmenter le timeout ne cree pas davantage de patrons. Cela laisse seulement plus de temps au solveur pour chercher une combinaison.

Le planning manuel du metier montre qu'une solution devrait exister avec :

- des coupures autorisees, penalisees mais non interdites ;
- une coupure pouvant aller jusqu'a 2 heures ;
- les stagiaires, apprentis et l'intendance ignores ;
- les jours de travail maximum lies au pourcentage conserves comme contrainte forte ;
- les remplacements de colloque exclus des changements ordinaires de groupe.

## Audit deja effectue

- Environ 1 628 454 patrons avec le jeu complet.
- Environ 444 090 patrons continus.
- Environ 1 184 245 patrons coupes.
- Environ 554 804 patrons mixtes.
- Environ 239 134 variantes de remplacement.
- Restreindre trop fortement les patrons peut rendre le modele artificiellement infaisable.
- Les journees uniquement continues sont insuffisantes : certaines coupures sont necessaires.
- Un prototype de moteur compact a approche une solution, mais il n'etait pas assez fiable pour etre livre et a ete retire.

## Prochaine etape recommandee

Ne pas repartir de zero et ne pas modifier les contraintes metier en premier.

1. Instrumenter la generation par educatrice, jour, groupe principal et type de patron afin d'identifier exactement les sources de l'explosion.
2. Eliminer uniquement les patrons domines : meme couverture et memes caracteristiques hard, mais cout superieur.
3. Conserver au moins un representant de chaque combinaison metier utile pour ne pas perdre de solution.
4. Tester la reduction sur `data/gwendo.json`, puis comparer le nombre de patrons et le statut avec le moteur actuel.
5. Une fois une solution hard valide obtenue rapidement, lancer une seconde phase d'amelioration des criteres soft.

Le point delicat est donc la reduction des patrons sans supprimer la solution manuelle possible. La prochaine intervention doit commencer par des mesures, puis ajouter une reduction conservative et testable.

## Reprise du 11 juin 2026

La capture du 10 juin a confirme un `MemoryError` pendant la construction de la matrice, apres generation de 1 628 454 patrons.

Corrections implementees :

- matrice construite directement en CSR avec des tableaux compacts, sans listes Python geantes ;
- coefficients de pourcentage regroupes par patron et par site ;
- index de couverture par site crees uniquement lorsqu'une regle de site les utilise ;
- groupe principal repris du dernier planning valide lorsque `fix_primary_groups_from_latest` vaut `true` ;
- `MemoryError` transforme en diagnostic lisible au lieu d'un traceback.

Mesure sur `data/gwendo.json` :

- avant : 1 628 454 patrons ;
- apres reprise des groupes principaux : 660 964 patrons, soit environ 59 % de moins ;
- le modele atteint HiGHS sans `MemoryError` ;
- essai volontairement arrete avant son terme pour limiter le temps de calcul.

Le groupe principal repris ne fige pas les jours, les horaires, les coupures, les groupes effectivement couverts ni les remplacements. Mettre `fix_primary_groups_from_latest` a `false` restaure la recherche complete des groupes principaux, avec un cout memoire nettement superieur.
