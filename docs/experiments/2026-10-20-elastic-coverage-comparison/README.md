# Comparaison initiale du prototype de couverture élastique

Protocole : trois graines (`1`, `17`, `43`), deux modes (compact strict et couverture élastique), 60 secondes par essai, soit six minutes nominales séquentielles. Aucun planning chargé comme hint ni fixé. Ordre alterné selon la graine, processus distincts, même code, données, règles, objectif de qualité et matériel. Les paramètres exacts et empreintes sont enregistrés au lancement.

Il s’agit d’un premier écran à 60 secondes, pas d’une preuve de supériorité ni d’une reproduction à 600 secondes du calcul précédent. Le moteur par patrons et l’interface Windows ne sont pas évalués ici. Les sources de production et sorties actives sont protégées par empreintes.

Validation préalable : 149 tests réussis en 34,761 s (`tests.log`), dont quinze protections et témoins du prototype. Le planning réel connu fixé conserve ses affectations, son score et un déficit nul. Référence de la méthode et détails : `docs/ELASTIC_COVERAGE.md`.

Reproduction depuis la racine dans un environnement avec les dépendances et OR-Tools :

```sh
python docs/experiments/2026-10-20-elastic-coverage-comparison/run.py
```

Résultats : campagne à exécuter après publication du prototype validé.
