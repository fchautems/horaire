# Solveur de planning creche

Application locale pour editer les donnees d'une creche et generer un planning hebdomadaire.

Le programme se base sur les sites, les groupes, les educateurs, les disponibilites, les besoins minimums de staffing, les regles de pourcentage par site, les colloques et le THE.

## Lancer l'application

Double-cliquer sur :

```text
lancer_editeur.bat
```

ou en ligne de commande :

```powershell
python creche_editor.py data\gwendo.json
```

## Lancer le solveur seul

```powershell
python solveur_v2.py --config config\solveur_config.json
```

Les resultats sont ecrits dans `outputs/`.

## Arborescence

```text
src/creche_planning/   code Python principal
config/                parametres du solveur
data/                  donnees JSON
docs/                  documentation utilisateur et regles metier
outputs/               resultats generes et anciens essais
```

Voir `docs/DOCUMENTATION_UTILISATEUR.md` pour la documentation metier et `docs/README_SOLVEUR_V2.md` pour les details de lancement.
