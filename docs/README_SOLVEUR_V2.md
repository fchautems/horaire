# Solveur creche v2

Ce solveur repart du JSON existant et remplace le vieux generateur aleatoire par un modele MILP avec SciPy/HiGHS. Le moteur par defaut construit des patrons de journee lisibles, au lieu d'assembler le planning par petits morceaux de 15 minutes.

## Lancer sur le fichier actuel

```powershell
python solveur_v2.py --config config\solveur_config.json
```

Ou double-cliquer sur `lancer_solveur.bat`.

Les fichiers de sortie sont horodates automatiquement, par exemple
`outputs\planning_gwendo_smooth_2026-05-29_16-30-12.json`, pour eviter d'ecraser les anciens plannings.
Le solveur produit aussi une vue HTML visuelle, par exemple
`outputs\planning_gwendo_visuel_2026-05-29_16-30-12.html`.
En plus des archives horodatees, il garde une copie fixe du dernier calcul :
`outputs\planning_gwendo_latest.json`, `outputs\planning_gwendo_latest.csv` et
`outputs\planning_gwendo_latest.html`.

## Lancer l'editeur JSON

```powershell
python creche_editor.py data\gwendo.json
```

Ou double-cliquer sur `lancer_editeur.bat`.

L'editeur permet d'afficher et modifier les sites, groupes, types, educateurs, regles horaires, regles de groupe, pourcentages, staffing, colloques et regles globales. Il contient aussi un onglet JSON brut, une validation des references, un onglet Planning qui recharge le dernier resultat calcule, et un bouton `Enregistrer + lancer solveur` qui utilise `config\solveur_config.json`.

## Documentation utilisateur

Lire `docs\DOCUMENTATION_UTILISATEUR.md`.

Cette documentation explique en langage non technique ce que le programme comprend des donnees, les fichiers importants, les sorties produites et chaque parametre de `config\solveur_config.json`.

La liste synthetique des regles hard et soft est dans `docs\REGLES_METIER.md`.

Le decoupage technique actuel est decrit dans `docs\ARCHITECTURE.md`.

## Ce qui est verifie

- couverture minimale par groupe et tranche de 15 minutes ;
- maximum de 3 personnes par groupe/tranche, sauf si une regle demande plus ;
- heures hebdomadaires selon les pourcentages, avec une tolerance de 3% arrondie par paliers de 15 minutes ;
- THE : 10% du contrat, colloques inclus, THE ordinaire invisible dans le planning et exclu de la couverture enfants ;
- maximum hebdomadaire absolu de 40h ;
- nombre maximal de jours travailles selon le taux, sauf exception `max_work_days` explicite ;
- maximum journalier ;
- un seul site par personne et par jour dans le solveur actuel ;
- colloques : le groupe concerne ne compte plus en couverture, une personne de chaque autre groupe remplace, et ces remplacements comptent dans les pourcentages du site ;
- groupe principal : chaque educateur a un groupe principal; le colloque de ce groupe est obligatoire, complet, et compte comme THE ;
- regles de pourcentage par site ;
- preferences horaires et de groupe en penalites soft.
- regles `hard` horaires/groupes controlees apres calcul ;
- changements de groupe intra demi-journee, coupures de plus de 1h30 et nombre de jours avec changement de groupe ;
- si un controle hard echoue, le statut devient `invalid` au lieu de `ok`.

## Ce que le moteur essaie d'ameliorer

- eviter les horaires coupes ;
- si une coupure est inevitable, reduire sa duree et la limiter a 1h30 par defaut ;
- condenser les temps partiels sur le minimum de jours possible, par exemple environ 3 jours pour un 55% ;
- garder un educateur le plus possible dans le meme groupe sur la semaine ;
- eviter qu'un changement de groupe exceptionnel se fasse dans la meme journee.

Le moteur `pattern_mip` construit directement des blocs de presence et choisit les groupes dans le meme calcul. Cela evite les plannings composes de petits morceaux de 15 minutes.

Ces points restent des preferences : la couverture des groupes, les colloques et les regles `hard` passent avant.

Si le maximum de jours travailles rend le probleme impossible, la configuration actuelle autorise une relance automatique avec cette limite assouplie mais tres fortement penalisee. Le planning reste alors `ok` seulement si toutes les autres regles strictes sont respectees, et les personnes au-dessus du maximum souhaite sont listees en avertissement.

## Notes sur les donnees

- Les regles de staffing qui se chevauchent sont interpretees comme des paliers de minimum : on garde le maximum, on ne les additionne pas.
- La donnee verifiee utilise `EDE`, `ASE` et `APE`. Aucun alias de type n'est applique par defaut.
- Les preferences qui vont jusqu'a `19:00` sont rognees a l'horizon reel du planning (`18:45`).
- Une regle horaire `positif hard` force une presence sur la plage, mais pas toute la plage. Pour dire "elle doit travailler lundi", mettre une plage qui couvre le lundi.
