# Prototype : faisabilité par couverture élastique

## Méthode et portée

Option expérimentale désactivée par défaut. Référence : [exemple officiel Gurobi workforce4](https://docs.gurobi.com/projects/examples/en/current/examples/python/workforce4.html), objectif de somme des écarts de couverture avant un objectif de qualité. Le principe est implémenté avec OR-Tools CP-SAT déjà utilisé par le projet ; aucune dépendance Gurobi ajoutée.

Le même constructeur du compact et le même validateur strict servent aux deux modes. Seules les bornes **minimums** de couverture des groupes et sites reçoivent des variables de déficit. Chaque déficit est exactement `max(0, besoin - présence)`, entier entre zéro et le besoin. Les bornes maximums de personnel et toutes les autres contraintes configurées restent identiques.

Phase I : minimiser la somme des déficits, sans objectif de préférences/confort. Aucun ancien planning n’est nécessaire. Pas d’hypothèses fixant temporairement les groupes dans cette phase ; les hints internes du moteur restent indicatifs. Un callback interrompt cette phase dès qu’un déficit total nul est rencontré.

À zéro : fixer la somme des déficits à zéro, revalider l’horaire avec toutes les règles hard, enregistrer seulement les candidats valides puis optimiser la qualité avec le temps global restant. Même avec des affectations fixées pour un témoin, les choix encore libres, notamment de groupe principal, peuvent être améliorés dans cette seconde phase.

Un déficit positif reste un **diagnostic invalide** : pas de phase de confort, pas de callback de checkpoint valide et pas de remplacement des sorties `latest`. Le validateur signale toujours les vrais défauts de couverture. L’orchestrateur conserve son mécanisme existant de protection d’un meilleur planning valide antérieur.

## Activation et reproductibilité

API du moteur compact :

```python
payload, bundle = make_ortools_slot_payload(
    data,
    time_limit=60,
    experimental_elastic_coverage=True,
    search_seed=17,
    # Autres paramètres métier identiques au lancement strict.
)
```

Configuration : `experimental_elastic_coverage: false` et `cp_sat_search_seed: null` par défaut. L’option s’applique aux appels compacts CP-SAT ; elle ne transforme pas le moteur par patrons ou les anciens moteurs SciPy. Pour un essai CLI isolé, utiliser une configuration `solver_engine: "cp-sat"` avec ses fichiers de sortie dans un dossier d’essai :

```sh
python -m creche_planning.solver --config chemin/config-essai.json --experimental-elastic-coverage --search-seed 17
```

Les paramètres de diagnostic désactivant les structures journalières, la stabilité par demi-journée, les qualifications, les plafonds journaliers ou les contrats hebdomadaires ne peuvent pas être combinés avec cette option ; `accept_invalid_for_hint=True` est également refusé. Les règles restent celles des paramètres métier explicites du lancement, qui doivent être enregistrés pour chaque comparaison.

Sans graine explicite, le chemin strict conserve les graines historiques ; avec `search_seed`, les variantes de stratégie reçoivent des décalages déterministes documentés dans le code. Le multithreading ne garantit pas des résultats identiques d’une exécution à l’autre.

## Résultats et unités

`elastic_coverage` expose le statut et le temps de première phase, sa borne, l’évolution des déficits, les lignes non couvertes et le délai jusqu’à zéro. `quality_phase_started` distingue la réparation de l’amélioration.

`total_deficit_slots` est la somme des manques par **ligne d’exigence**. `deficit_requirement_minutes` multiplie cette somme par le pas de grille. Les lignes groupe et site peuvent se recouvrir : ces valeurs ne représentent pas des heures de personnel distinctes. Chaque ligne contient son périmètre, jour, site/groupe, heure, besoin, présence et manque.

`objective` reste le score de qualité recalculé sur l’affectation, y compris dans un diagnostic ; il ne sert pas à accepter un diagnostic. `solver_reported_objective_kind` identifie si l’objectif scalaire rapporté par CP-SAT correspond aux déficits de première phase ou à la qualité de seconde phase.

`UNKNOWN` signifie qu’aucune solution de la phase n’a été trouvée dans son budget. Un diagnostic déficitaire sous timeout ne prouve pas l’infaisabilité stricte. Zéro constitue directement la borne inférieure de l’objectif de déficit ; aucune preuve supplémentaire d’optimalité de cette première phase n’est requise.

## Contrôles

`tests/test_elastic_coverage.py` couvre : déficit exact et diagnostic non publié comme valide ; valeur par défaut stricte ; absence de compensation par les préférences ; couverture groupe/site séparée ; contrats, qualifications, indisponibilités, plafonds journaliers/hebdomadaires, maximum de jours, maxima de personnel, coupures de 90 minutes, trajets et colloques/THE ; veto du validateur strict ; activation CLI et préservation des sorties latest.

Le candidat réel du 20 octobre est aussi fixé dans les deux variantes : affectations et score identiques, déficit nul. Ceci valide sa représentation et les protections, pas la génération libre.

La comparaison depuis zéro et ses limites figurent dans `docs/experiments/2026-10-20-elastic-coverage-comparison/` une fois les essais terminés. Le prototype reste désactivé tant que les mesures ne justifient pas une adoption.
