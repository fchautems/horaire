# Réparation locale des cinq créneaux — 19 octobre 2026

## Résultat

Une réorganisation locale du planning historique avec délais de trajet produit un **planning complet valide** selon les règles actuelles. Les cinq déficits de couverture disparaissent, sans erreur de déplacement ni autre erreur hard.

Ce résultat est confirmé indépendamment par les trois chemins de contrôle :

- validateur : statut `ok`, zéro erreur ;
- CP-SAT avec planning fixé : `OPTIMAL`, mêmes affectations par créneau ;
- moteur par patrons avec journées fixées : `Optimal`, mêmes affectations par créneau.

Le score commun recalculé est **743 872** pour le candidat, CP-SAT et les patrons. Les exports CSV et HTML décrivent le candidat comme valide. Aucun calcul global n'a été lancé.

## Réorganisation minimale testée

| Personne | Jour | Modification |
|---|---|---|
| X | lundi | début Grands avancé de 13:15 à 13:00 |
| Natacha | mardi | fin du matin avancée de 11:45 à 11:30 ; reprise Trotteur avancée de 13:15 à 13:00 |
| A repourvoir | mardi | début Trotteur avancé de 11:45 à 11:30 |
| Emilie | mardi | fin Nurserie retardée de 14:00 à 14:15 |
| Léa | mardi | fin Trotteur retardée de 14:15 à 14:30 |
| Tara | jeudi | début du matin retardé de 07:45 à 08:00 ; reprise Grands avancée de 13:15 à 13:00 |

Natacha et Tara déplacent chacune quinze minutes dans leur journée : leur total quotidien ne change pas. Le quart d'heure retiré à Natacha est repris par « A repourvoir ». X, A repourvoir, Emilie et Léa ajoutent chacun quinze minutes, dans les tolérances contractuelles configurées.

## Justification et essais discriminants

Le planning témoin initial reproduit exactement les cinq erreurs attendues : Grands lundi 13:00, Nurserie mardi 14:00, Trotteur mardi 13:00 et 14:15, Grands jeudi 13:00.

Les extensions directes de X, Emilie et Léa suppriment leur déficit sans nouvel écart. Les extensions directes de Natacha et Tara dépassent d'abord la limite quotidienne de 8,5 heures. Tara peut restituer quinze minutes le matin sans perdre de couverture. Pour Natacha, retirer un quart d'heure à l'une des extrémités crée un nouveau déficit Trotteur ; avancer « A repourvoir » à 11:30 couvre celui de 11:30 et permet de déplacer le quart d'heure de Natacha vers 13:00.

## Cohérence des moteurs et exports

Le moteur par patrons omet le libellé `children` sur les blocs ordinaires reconstruits ; la comparaison est donc faite par affectations de créneau après normalisation de ce libellé. Horaires, groupes, sites, colloques et remplacements sont identiques. Les deux moteurs et le validateur utilisent les mêmes groupes principaux lors du recalcul du score.

L'export HTML indique : règles hard OK, six blocs de remplacement pour 4,75 h, marge de couverture de 14,5 heures-personne. Les trajets minimaux restent exclus des coupures classiques comme prévu par la règle corrigée.

## Portée et limites

Le candidat est conservé uniquement dans ce dossier d'expérience. Il ne remplace aucun planning actif et ne modifie ni les données, ni la configuration, ni le code de production. Les empreintes des fichiers protégés sont identiques avant et après.

Il s'agit d'une réparation locale d'un planning historique, pas d'une preuve que la recherche libre retrouvera ce candidat ni d'une preuve de performance. Aucun nouveau bug n'est démontré par ce diagnostic. La prochaine action utile est de décider si ce candidat peut servir de hint à une optimisation courte ou s'il doit seulement rester comme témoin de faisabilité.

## Preuves

- `run.py` : reconstruction, modifications et assertions.
- `candidate.json`, `candidate.csv`, `candidate.html` : candidat revalidé et exports.
- `cp-fixed.json`, `patterns-fixed.json` : validations indépendantes des moteurs.
- `changes.json` : huit changements de bornes horaires.
- `conditions.json`, `integrity.json`, `summary.json`, `run.log`, `evidence.json` : environnement, empreintes et synthèse.
