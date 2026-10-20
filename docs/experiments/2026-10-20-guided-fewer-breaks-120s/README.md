# Recherche guidée de coupures plus courtes — 20 octobre 2026

## Résultat

Une recherche CP-SAT guidée de 120 secondes, démarrée depuis le candidat hard-valide du 19 octobre, a trouvé un planning valide avec **2 h 15 de coupures classiques en moins**.

| Mesure | Départ | Résultat |
| --- | ---: | ---: |
| Journées avec coupure | 8 | 8 |
| Durée totale des coupures | 11 h 00 | 8 h 45 |
| Coupure maximale | 90 min | 90 min |
| Score commun | 760979 | 702701 |
| Erreurs hard | 0 | 0 |

Le nombre de journées coupées ne baisse pas pendant ce budget court. La durée totale baisse de 135 minutes :

- Tara jeudi : 90 → 75 minutes ;
- Léa jeudi : 90 → 15 minutes ;
- Emilie vendredi : 90 → 60 minutes ;
- Priscila mardi : 75 → 60 minutes.

Les quatre autres coupures restent inchangées en durée : Natacha mardi 90 minutes, Céline jeudi 90 minutes, Magali lundi 75 minutes et Magali mercredi 60 minutes.

## Conditions et contrôles

- Horaires et affectations libres ; candidat précédent utilisé uniquement comme hint.
- Maximum hard de coupure : 90 minutes, sans assouplissement.
- Priorité de recherche renforcée sur le nombre de périodes, puis la durée des coupures ; configuration de production inchangée.
- CP-SAT : `FEASIBLE`, 26 solutions d'optimisation signalées en 111,744 s après une première solution en 7,602 s.
- Revalidation finale : aucune erreur hard ni de déplacement.
- Moteur par patrons avec le résultat fixé : `Optimal` en 0,013 s, mêmes affectations par créneau et même score 702701.
- Sources, données, configuration et sorties actives inchangées pendant l'essai. Aucun planning actif remplacé.

## Limites

Le statut `FEASIBLE` ne prouve pas l'optimalité. L'absence de candidat avec moins de huit journées coupées dans ces 120 secondes ne prouve pas qu'il n'en existe pas. Le résultat modifie de nombreuses journées, car il s'agit d'une optimisation globale guidée et non d'une réparation locale.

## Preuves

- `conditions.json` : paramètres, version et empreintes initiales ;
- `summary.json` : comparaison et statistiques ;
- `result.json`, `result.csv`, `result.html` : résultat sélectionné ;
- `raw-result.json` et `cp-sat.log` : sortie et journal CP-SAT ;
- `patterns-fixed.json` et `cross-check.json` : contrôle par patrons ;
- `integrity.json` : contrôle des fichiers protégés ;
- `run.py` et `verify.py` : reproduction ;
- `evidence.json` : empreintes SHA-256.

## Horaires individuels — ajout du 20 octobre 2026

`result.html` contient aussi une section **Horaires individuels**, accessible par un lien en haut du rapport, puis une fiche hebdomadaire par personne. Chaque fiche détaille les cinq jours, les plages dans l'ordre chronologique, les sites et groupes, les colloques, les remplacements et les jours libres. Les heures visibles sont séparées du THE hors colloque non planifié ; les totaux hebdomadaires proviennent du contrôle existant.

Cet ajout est également intégré au générateur HTML pour les prochains exports. Le rapport est régénéré depuis le même `result.json`, sans nouveau calcul ni modification des horaires. L'empreinte de `result.html` dans `evidence.json` est actualisée ; les traces du calcul initial restent historiques.

