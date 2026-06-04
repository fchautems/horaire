# Programme d'horaires de creche

## 1. Ce que le programme fait

Le programme lit un fichier de donnees, par exemple `gwendo.json`, puis il essaie de construire un horaire du lundi au vendredi.

Il ne devine pas l'organisation de la creche. Il se base uniquement sur ce qui est ecrit dans le fichier JSON :

- les sites, par exemple `haut` et `bas` ;
- les groupes d'enfants, par exemple `Nurserie`, `Trotteur`, `Grands` ;
- les educateurs, leur taux de travail et leur type de formation ;
- les besoins de personnel par groupe et par tranche horaire ;
- les regles de pourcentage de types d'educateurs par site ;
- les colloques, c'est-a-dire les moments ou un groupe n'est pas disponible et doit etre remplace ;
- les preferences horaires ou de groupe.

Le resultat est un planning qui dit, pour chaque educateur et chaque jour, quand il travaille, sur quel site, et dans quel groupe.

Le programme refait aussi des controles apres calcul. Il separe maintenant les vraies erreurs bloquantes des alertes non bloquantes. Si une regle `hard` est violee, le planning est marque `invalid` et ne doit pas etre utilise tel quel.

Si les donnees ne representent pas correctement la realite, le planning sera mathematiquement correct mais pas forcement utile. C'est pour cela qu'il faut d'abord verifier que les donnees sont bien comprises.

## 2. Comment le programme comprend les donnees

### Sites

Un site est un lieu physique, par exemple `haut` ou `bas`.

Chaque site a une heure d'ouverture et une heure de fermeture. Dans le fichier actuel, les sites ouvrent a `06:45` et ferment a `18:45`.

### Groupes

Un groupe appartient a un seul site.

Exemple :

- `Nurserie` est sur le site `bas` ;
- `Trotteur` est sur le site `bas` ;
- `Grands` est sur le site `haut`.

Quand le solveur place une personne sur un groupe, il sait donc automatiquement sur quel site elle travaille.

### Educateurs

Chaque educateur a :

- un nom ;
- un pourcentage de travail ;
- un type, par exemple `EDE`, `ASE`, `APE`.
- eventuellement un maximum de jours de travail (`max_work_days`) si l'on veut declarer une exception.

Le programme considere que `100% = 40 heures par semaine`.

Exemples :

- `100%` donne `40 h` ;
- `80%` donne `32 h` ;
- `50%` donne `20 h`.

Avec le reglage actuel, le solveur vise ces heures avec une petite tolerance configuree. Le total hebdomadaire d'une personne correspond a :

```text
heures enfants visibles + THE
```

Le THE hors colloque n'apparait pas dans le planning visible, mais il compte bien dans le total contractuel.

### Temps hors enfants (THE)

Le programme considere que chaque educateur a `10%` de son temps contractuel en THE.

Exemples :

- `100% = 40 h` -> `4 h` de THE et environ `36 h` aupres des enfants ;
- `80% = 32 h` -> `3 h 15` de THE et environ `28 h 45` aupres des enfants ;
- `50% = 20 h` -> `2 h` de THE et environ `18 h` aupres des enfants.

Les colloques font partie du THE. Si une personne est en colloque, ce temps est visible comme `colloque` et ne compte pas dans la couverture enfants.

Le reste du THE est invisible : il sert uniquement au controle des heures. Il ne cree pas de ligne dans le planning, parce que le besoin exprime est de voir surtout les presences enfants.

Le programme limite aussi le nombre de jours travailles selon le taux. Par defaut, il calcule :

```text
maximum de jours = plafond(heures hebdo / maximum d'heures par jour)
```

Avec `max_daily_hours = 8.5`, cela donne par exemple :

- `60% = 24 h` -> maximum `3` jours ;
- `50% = 20 h` -> maximum `3` jours ;
- `40% = 16 h` -> maximum `2` jours ;
- `80% = 32 h` -> maximum `4` jours.

Si une personne accepte explicitement plus de jours, on peut ajouter `max_work_days` dans sa fiche educateur. Exemple :

```json
{
    "name": "Tara",
    "percentage": 60,
    "type": "ASE",
    "max_work_days": 5
}
```

### Besoins de personnel

Les besoins sont dans la partie `rules_site_schedule`.

Exemple : si le fichier dit que `Nurserie` demande `2` personnes de `08:30` a `18:00`, le programme doit placer au moins deux educateurs sur `Nurserie` pendant cette periode.

Important : quand plusieurs regles se chevauchent sur le meme groupe, le programme garde le plus grand minimum, il ne les additionne pas.

Exemple :

- `Grands` demande `2` personnes de `08:15` a `18:00` ;
- `Grands` demande `3` personnes de `11:00` a `12:00`.

Le programme comprend : `3` personnes entre `11:00` et `12:00`, pas `5`.

### Pourcentages par site

Les regles de pourcentage disent qu'un site doit avoir une certaine proportion de types d'educateurs sur la semaine.

Exemple :

- `EDE min 40% sur haut` signifie qu'au moins 40% des heures travaillees sur le site `haut` doivent etre faites par des personnes de type `EDE`.

Ces regles sont strictes. Si elles sont impossibles, le solveur ne doit pas inventer une solution.

### Colloques

Les colloques sont dans la partie `rules_colloques`.

Exemple :

```json
{
    "group": "Trotteur",
    "day": "lundi",
    "start": "13:15",
    "end": "14:00"
}
```

Le programme comprend ceci comme suit :

- les personnes qui sont dans le groupe en colloque ne comptent plus comme couverture enfants pendant cette plage ;
- une personne de chaque autre groupe doit venir remplacer le groupe en colloque ;
- ce remplacement est marque comme exceptionnel et ne compte pas comme un changement de groupe interdit ;
- par contre, le remplacement compte bien dans les controles de couverture et dans les pourcentages `EDE` / `ASE` / `APE` du site ou il remplace.

Autrement dit, le colloque ne sert pas a contourner les regles de securite : il change seulement qui couvre le groupe pendant ce moment-la.

### Preferences

Les regles horaires et de groupe sont des preferences, sauf si elles sont marquees `hard`.

- `negatif hard` signifie interdit ;
- `positif hard` signifie que la personne doit travailler au moins une partie de cette plage. Si la plage couvre toute la journee, cela veut dire que la personne doit travailler ce jour-la ;
- `soft` signifie preference : le solveur essaie de la respecter, mais peut l'enfreindre si c'est necessaire.

Pour les regles de groupe, le programme utilise maintenant une notion de groupe principal :

- chaque educateur a un groupe principal pour la semaine ;
- une regle groupe `positif hard` impose ce groupe principal ;
- une regle groupe `negatif hard` interdit ce groupe principal ;
- une regle groupe `soft` oriente fortement le choix, sans le rendre obligatoire.

Le jour du colloque du groupe principal, l'educateur doit travailler dans ce groupe et participer au colloque complet. Ce colloque compte comme THE et ne compte pas comme couverture enfants.

Les remplacements de colloque restent separes : pendant un colloque, une personne de chaque autre groupe vient couvrir le groupe concerne. Ces remplacements comptent dans la couverture enfants et dans les pourcentages du site.

Avec le parametre actuel `min_daily_hours: 2`, une personne forcee a travailler un jour ne recevra pas une mini-presence de 15 minutes : si elle travaille, elle doit faire au moins 2 heures ce jour-la.

## 3. Point verifie : types d'educateurs

La donnee utilise les types `EDE`, `ASE` et `APE`.

Le type `ADE` a ete supprime des donnees. Le solveur ne le remplace donc plus automatiquement.

Si une regle contient a nouveau un type inconnu, le programme doit l'afficher comme avertissement, afin que la donnee soit corrigee explicitement.

## 4. Fichiers importants

### `data/gwendo.json`

C'est le fichier de donnees : sites, groupes, educateurs, regles.

### `creche_editor.py`

C'est l'editeur graphique du fichier JSON.

Lancement :

```powershell
python creche_editor.py data\gwendo.json
```

Ou double-clic sur :

```text
lancer_editeur.bat
```

Dans l'editeur, le bouton `Enregistrer + lancer solveur` permet de calculer directement le planning :

- il enregistre d'abord le JSON ouvert ;
- il lit les reglages de `config\solveur_config.json` ;
- il cree des fichiers de sortie horodates ;
- il lance le solveur ;
- il affiche le planning dans l'onglet `Planning`.

### `solveur_v2.py`

C'est le programme qui calcule l'horaire.

### `config/solveur_config.json`

C'est le fichier de reglages du solveur.

### `lancer_solveur.bat`

C'est le lanceur simple pour calculer un planning avec les reglages du fichier `config\solveur_config.json`.

Double-cliquer dessus suffit.

## 5. Sorties produites

Avec la configuration actuelle, le solveur produit des fichiers horodates pour ne pas ecraser les anciens resultats.

Exemple :

```text
outputs\planning_gwendo_smooth_2026-05-29_16-30-12.json
outputs\planning_gwendo_smooth_2026-05-29_16-30-12.csv
outputs\planning_gwendo_visuel_2026-05-29_16-30-12.html
```

Il produit aussi une copie fixe du dernier resultat :

```text
outputs\planning_gwendo_latest.json
outputs\planning_gwendo_latest.csv
outputs\planning_gwendo_latest.html
```

L'editeur utilise `outputs\planning_gwendo_latest.json` pour recharger automatiquement le dernier planning calcule au demarrage.

### `planning_gwendo_smooth.json`

Fichier complet du planning, avec les controles de verification.

Avec l'horodatage actif, le nom exact contient aussi la date et l'heure.

### `planning_gwendo_smooth.csv`

Fichier plus simple a ouvrir dans Excel.

Avec l'horodatage actif, le nom exact contient aussi la date et l'heure.

Chaque ligne contient :

- educateur ;
- jour ;
- site ;
- groupe ;
- debut ;
- fin ;
- heures ;
- activite eventuelle, par exemple `colloque` ou `remplacement_colloque`.

Le THE invisible n'est pas ajoute comme ligne CSV. Il apparait dans le JSON de resultat et dans le resume des heures.

Si le solveur ne trouve pas de planning valide, le CSV contient une ligne de diagnostic au lieu de laisser un ancien planning ambigu.

### `planning_gwendo_visuel.html`

Vue visuelle du planning dans un navigateur.

Elle montre chaque jour, chaque groupe, les tranches de 15 minutes, les personnes presentes et le besoin minimum. Une case rouge signale une sous-couverture ; une case orange signale un depassement du maximum usuel.

Elle affiche aussi un tableau recapitulatif des heures : total contractuel, heures enfants, THE total, part colloque et THE invisible.

## 6. Parametres du fichier `config/solveur_config.json`

### `input_json`

Fichier de donnees a lire.

Valeur actuelle :

```json
"input_json": "../data/gwendo.json"
```

### `output_json`

Fichier de sortie complet.

Valeur actuelle :

```json
"output_json": "../outputs/planning_gwendo_smooth.json"
```

### `csv_output`

Fichier CSV pour Excel.

Valeur actuelle :

```json
"csv_output": "../outputs/planning_gwendo_smooth.csv"
```

### `html_output`

Fichier HTML visuel.

Valeur actuelle :

```json
"html_output": "../outputs/planning_gwendo_visuel.html"
```

### `write_latest_outputs`

Demande au solveur de garder une copie fixe du dernier resultat, en plus des fichiers horodates.

Valeur actuelle :

```json
"write_latest_outputs": true
```

Quand ce parametre vaut `true`, l'editeur peut retrouver automatiquement le dernier planning calcule.

### `latest_output_json`, `latest_csv_output`, `latest_html_output`

Noms des fichiers fixes qui contiennent toujours le dernier resultat.

Valeurs actuelles :

```json
"latest_output_json": "../outputs/planning_gwendo_latest.json",
"latest_csv_output": "../outputs/planning_gwendo_latest.csv",
"latest_html_output": "../outputs/planning_gwendo_latest.html"
```

### `timestamp_outputs`

Ajoute automatiquement la date et l'heure aux fichiers de sortie.

Valeur actuelle :

```json
"timestamp_outputs": true
```

Si ce parametre vaut `true`, chaque lancement cree de nouveaux fichiers.

Si ce parametre vaut `false`, le solveur reutilise toujours les memes noms et peut donc ecraser le planning precedent.

### `timestamp_format`

Format utilise pour la date et l'heure dans le nom du fichier.

Valeur actuelle :

```json
"timestamp_format": "%Y-%m-%d_%H-%M-%S"
```

Cela donne par exemple :

```text
2026-05-29_16-30-12
```

Il vaut mieux garder ce format, car il se trie bien dans l'explorateur Windows.

### `solver_engine`

Methode de calcul utilisee.

Valeur actuelle :

```json
"solver_engine": "pattern_mip"
```

`pattern_mip` construit des patrons de journee lisibles : un vrai bloc de travail, ou exceptionnellement deux blocs avec une coupure limitee. Cela evite les plannings en petits morceaux de 15 minutes et permet de controler directement les changements de groupe.

### `time_limit_seconds`

Temps maximum donne au solveur principal.

Valeur actuelle :

```json
"time_limit_seconds": 300
```

Augmenter cette valeur peut aider si le solveur ne trouve pas de solution ou si les donnees deviennent plus grosses. Ici la valeur a ete montee a 300 secondes parce que le planning est plutot calcule ponctuellement.

Le moteur actuel respecte cette limite pour la resolution principale. Il peut y avoir un petit temps en plus pour preparer les patrons de journee et ecrire les fichiers.

### `quality_gap`

Marge de qualite acceptee par le solveur.

Valeur actuelle :

```json
"quality_gap": 0.05
```

Pour une personne non technique :

- `0.10` = plus rapide, qualite un peu moins poussee ;
- `0.05` = bon compromis ;
- `0.01` = plus strict, souvent plus lent.

### `weekly_mode`

Mode de calcul des heures hebdomadaires.

Valeur actuelle :

```json
"weekly_mode": "exact"
```

Valeurs possibles :

- `exact` : chaque educateur doit atteindre exactement ses heures ;
- `maximum` : chaque educateur ne doit pas depasser ses heures, mais peut faire moins.

Avec le moteur actuel `pattern_mip`, la logique utile est surtout controlee par `weekly_hours_tolerance_percent`, `weekly_hours_tolerance_step_minutes`, `the_percent` et le maximum absolu de 40 h.

### `weekly_hours_tolerance_percent`

Tolerance acceptee au controle final sur les heures hebdomadaires.

Valeur actuelle :

```json
"weekly_hours_tolerance_percent": 3.0
```

Exemple : pour un contrat a 30 h, `3.0` donne une tolerance theorique de 54 minutes. Avec le palier actuel de 15 minutes, le programme retient 45 minutes afin de ne pas depasser la limite de 3%.

Le solveur continue a chercher un planning proche du taux contractuel. La tolerance sert a laisser de la souplesse quand les contraintes de couverture, de groupe et de colloque l'exigent.

### `weekly_hours_tolerance_step_minutes`

Palier utilise pour arrondir la tolerance hebdomadaire.

Valeur actuelle :

```json
"weekly_hours_tolerance_step_minutes": 15
```

Avec `15`, le solveur a plus de finesse qu'avec des paliers de 30 minutes.

### `absolute_max_weekly_hours`

Maximum absolu d'heures par semaine.

Valeur actuelle :

```json
"absolute_max_weekly_hours": 40
```

Cette limite est stricte : meme avec la tolerance contractuelle, personne ne doit depasser 40 h par semaine.

### `the_enabled`

Active le calcul du temps hors enfants.

Valeur actuelle :

```json
"the_enabled": true
```

Quand ce parametre vaut `true`, les heures contractuelles sont separees en deux parties : temps aupres des enfants et THE.

### `the_percent`

Part du contrat reservee au THE.

Valeur actuelle :

```json
"the_percent": 10.0
```

Exemple : pour un contrat de `40 h`, le programme reserve `4 h` de THE. La capacite maximum aupres des enfants devient donc environ `36 h`, sous reserve de la tolerance hebdomadaire.

### `the_colloques_count`

Indique si les colloques comptent comme THE.

Valeur actuelle :

```json
"the_colloques_count": true
```

Quand ce parametre vaut `true`, une personne en colloque est consideree comme en THE pendant cette plage. Elle ne compte pas dans la couverture enfants pendant le colloque.

### `the_regular_is_invisible`

Indique que le THE hors colloque n'est pas affiche dans le planning.

Valeur actuelle :

```json
"the_regular_is_invisible": true
```

Ce parametre documente le choix metier actuel : le planning visuel montre les presences enfants, les colloques et les remplacements de colloque, mais pas les moments de THE ordinaire.

### `fix_primary_groups_from_latest`

Utilise le dernier planning calcule pour proposer les groupes principaux de depart.

Valeur actuelle :

```json
"fix_primary_groups_from_latest": true
```

Ce reglage rend le calcul beaucoup plus rapide. Le programme garde ces groupes quand ils sont compatibles avec les regles hard et les jours de colloque. Si un groupe suggere est impossible, par exemple parce que la personne est indisponible le jour du colloque, il l'ignore et choisit un groupe compatible.

### `enforce_absolute_max_weekly_hours`

Active le controle du maximum absolu hebdomadaire.

Valeur actuelle :

```json
"enforce_absolute_max_weekly_hours": true
```

### `smooth`

Demande au programme de rendre le planning plus lisible.

Valeur actuelle :

```json
"smooth": true
```

Avec le moteur actuel `pattern_mip`, la lisibilite est integree directement au calcul : le programme choisit des patrons de journee plutot que des affectations tranche par tranche.

### `smooth_time_limit_seconds`

Ancien temps donne au lissage.

Valeur actuelle :

```json
"smooth_time_limit_seconds": 30
```

Avec `solver_engine: "pattern_mip"`, ce parametre est garde pour compatibilite mais le temps principal est surtout controle par `time_limit_seconds`.

### `smooth_split_shift_weight`

Poids utilise pour eviter les horaires coupes.

Valeur actuelle :

```json
"smooth_split_shift_weight": 120
```

Plus cette valeur est haute, plus le solveur evitera de faire travailler une personne en plusieurs blocs separes dans la meme journee. Ce n'est pas une interdiction absolue : si une coupure est necessaire pour couvrir les groupes et les taux horaires, le programme peut quand meme la faire.

### `smooth_split_gap_weight`

Poids utilise pour raccourcir le trou entre deux blocs de travail.

Valeur actuelle :

```json
"smooth_split_gap_weight": 4
```

Ce parametre sert surtout quand un horaire coupe est inevitable. Le solveur essaie alors de faire la coupure la plus courte possible.

### `smooth_max_split_gap_minutes`

Duree maximale autorisee pour une coupure.

Valeur actuelle :

```json
"smooth_max_split_gap_minutes": 90
```

Avec cette valeur, si une journee doit etre coupee, la coupure ne doit pas depasser 1h30. Le controle final signale aussi toute coupure plus longue qui resterait dans le planning.

### `smooth_group_switch_day_weight`

Poids utilise pour eviter qu'une personne change de groupe dans la meme journee.

Valeur actuelle :

```json
"smooth_group_switch_day_weight": 8
```

Plus cette valeur est haute, plus le programme prefere une journee simple, par exemple toute la journee en `Nurserie`, plutot qu'une journee coupee entre `Nurserie` et `Trotteur`.

### `smooth_same_group_week_weight`

Poids utilise pour garder chaque educateur autant que possible dans le meme groupe sur la semaine.

Valeur actuelle :

```json
"smooth_same_group_week_weight": 0.4
```

Le programme choisit d'abord un groupe principal pour chaque educateur. Il utilise les regles de groupe positives s'il y en a, sinon il regarde le groupe dans lequel l'educateur travaille le plus dans la premiere solution. Ensuite, pendant le lissage, il penalise les affectations dans les autres groupes.

Si une personne doit exceptionnellement changer de groupe dans la semaine, le parametre precedent (`smooth_group_switch_day_weight`) aide a eviter que ce changement arrive sous forme de melange dans une meme journee.

### `compact_work_days`

Demande au solveur de regrouper les heures sur le moins de jours possible.

Valeur actuelle :

```json
"compact_work_days": true
```

Le programme calcule automatiquement un maximum de jours a partir du taux de travail et du maximum journalier. Par exemple, avec un maximum de 8h30 par jour, un contrat d'environ 55% correspond a environ 22h par semaine, donc un maximum de 3 jours.

Avec le parametre `hard_max_work_days`, cette limite devient une vraie contrainte : si les besoins de couverture obligent a repartir une personne sur plus de jours, le solveur doit dire que le planning est impossible, sauf si une exception `max_work_days` est ecrite sur cette personne.

### `hard_max_work_days`

Transforme la limite du nombre de jours en contrainte stricte.

Valeur actuelle :

```json
"hard_max_work_days": true
```

Quand ce parametre vaut `true`, un 60% ne peut pas etre etale sur 5 jours par hasard. Pour l'autoriser, il faut l'ecrire explicitement dans la fiche de l'educateur avec `max_work_days`.

### `relax_work_days_if_infeasible`

Autorise une relance automatique si le maximum de jours rend le planning impossible.

Valeur actuelle :

```json
"relax_work_days_if_infeasible": true
```

Le solveur essaie d'abord de respecter strictement `hard_max_work_days`. Si aucune solution n'existe, il relance en gardant toutes les autres regles strictes, mais en transformant le maximum de jours en preference tres forte. Le resultat affiche alors un avertissement avec les personnes qui depassent leur maximum souhaite.

Ce comportement est utile quand une regle obligatoire, par exemple un colloque, rend le planning strictement impossible sans ajouter un jour a quelqu'un.

### `relaxed_work_day_weight`

Poids utilise pendant cette relance assouplie.

Valeur actuelle :

```json
"relaxed_work_day_weight": 500
```

Plus cette valeur est haute, plus le solveur evite les jours supplementaires. Il ne les utilise que si c'est necessaire pour garder un planning valide.

### `compact_work_day_weight`

Poids donne a la condensation des jours de travail.

Valeur actuelle :

```json
"compact_work_day_weight": 45
```

Plus cette valeur est haute, plus le solveur essaie d'eviter d'ajouter un jour de travail a une personne deja a temps partiel.

### `compact_part_time_priority`

Donne la priorite aux petits taux dans la condensation des jours.

Valeur actuelle :

```json
"compact_part_time_priority": true
```

Quand ce parametre est actif, un jour supplementaire coute plus cher pour un petit taux que pour un grand taux. Cela aide a obtenir, par exemple, des 50-60% sur environ 3 jours quand les besoins de couverture le permettent.

### `weekly_stability`

Demande au solveur de chercher une variante plus stable sur la semaine.

Valeur actuelle :

```json
"weekly_stability": true
```

Avec le moteur actuel, la stabilite de semaine est deja prise en compte dans les couts du calcul. Les regles de groupe positives servent de groupe principal quand elles existent.

### `main_group_day_weight`

Poids general donne a l'idee "un changement de groupe doit rester exceptionnel".

Valeur actuelle :

```json
"main_group_day_weight": 80
```

Ce parametre sert de reference pour la stabilite hebdomadaire. Plus il est haut, plus le programme essaie d'eviter qu'une personne parte regulierement dans un autre groupe.

### `main_group_slot_weight`

Poids par tranche de 15 minutes passee hors du groupe principal.

Valeur actuelle :

```json
"main_group_slot_weight": 3
```

Augmenter cette valeur rend les changements de groupe plus rares, mais peut aussi rendre le calcul plus long ou produire des horaires moins jolis. Le programme compare donc la variante stabilisee avec la variante de base avant de choisir.

### `main_site_day_weight`

Poids utilise pour eviter les changements de site.

Valeur actuelle :

```json
"main_site_day_weight": 100
```

Pour l'instant, ce poids est garde dans la configuration pour les evolutions suivantes. Le comportement principal actuel se concentre surtout sur la stabilite du groupe.

### `half_day_split_time`

Heure qui separe le matin et l'apres-midi pour les controles de changement de groupe.

Valeur actuelle :

```json
"half_day_split_time": "12:30"
```

Le programme controle qu'une personne ne change pas de groupe a l'interieur d'une meme demi-journee. Changer entre le matin et l'apres-midi reste possible si le planning l'exige.

### `max_weekly_group_exception_days`

Nombre maximal de jours par semaine ou une personne peut avoir plusieurs groupes dans la meme journee.

Valeur actuelle :

```json
"max_weekly_group_exception_days": 1
```

Si les donnees rendent cette regle impossible, le controle final le signale explicitement dans les erreurs de verification.

### `min_daily_hours`

Si une personne travaille un jour, elle doit travailler au moins ce nombre d'heures.

Valeur actuelle :

```json
"min_daily_hours": 2
```

Cela evite les journees absurdes de 15 ou 30 minutes.

### `fast_feasible`

Mode rapide qui cherche surtout une solution valide.

Valeur actuelle :

```json
"fast_feasible": false
```

Il vaut mieux garder `false` avec `smooth: true`.

### `structured`

Mode plus strict : au plus un groupe par jour et au plus deux blocs par jour.

Valeur actuelle :

```json
"structured": false
```

Ce mode est interessant en theorie, mais peut rendre le probleme trop difficile ou impossible selon les donnees.

### `max_blocks_per_day`

Nombre maximal de blocs de travail par personne et par jour.

Valeur actuelle :

```json
"max_blocks_per_day": 2
```

Le moteur actuel genere au maximum deux blocs par jour. En pratique, il cherche d'abord des journees en un seul bloc et n'utilise une coupure que si cela aide a respecter les autres contraintes.

### `type_aliases`

Permet de dire que deux noms de type doivent etre compris comme equivalents.

Valeur actuelle :

```json
"type_aliases": {}
```

Dans l'usage normal, ce parametre doit rester vide. Si un type est mal ecrit dans le JSON, il vaut mieux corriger la donnee plutot que cacher l'erreur avec un alias.

## 7. Comment utiliser le tout

### Modifier les donnees

Double-cliquer sur :

```text
lancer_editeur.bat
```

Quand le solveur est lance depuis l'editeur, une fenetre de progression indique l'etape en cours, le temps ecoule et les messages principaux du calcul.

La liste lisible des regles metier est dans :

```text
docs\REGLES_METIER.md
```

Modifier puis enregistrer.

### Generer un planning

Double-cliquer sur :

```text
lancer_solveur.bat
```

Ou, depuis l'editeur, cliquer sur :

```text
Enregistrer + lancer solveur
```

### Lire le resultat

Ouvrir :

```text
planning_gwendo_smooth.csv
```

ou consulter l'onglet Planning dans l'editeur.

## 8. Quand faut-il modifier le programme ?

Il faut modifier le programme si une phrase ci-dessus ne correspond pas a la vraie organisation.

Exemples :

- les regles qui se chevauchent doivent s'additionner au lieu de prendre le maximum ;
- une personne peut changer de site dans la meme journee ;
- les heures hebdomadaires doivent etre des maximums et pas des objectifs exacts ;
- un nouveau type d'educateur doit etre gere comme categorie distincte ;
- il faut des vrais shifts fixes predefinis, par exemple ouverture, fermeture, coupe.

Dans ces cas, ce n'est pas seulement un parametre : c'est la logique de calcul qu'il faut adapter.
