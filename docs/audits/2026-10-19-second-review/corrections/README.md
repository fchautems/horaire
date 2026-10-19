# Corrections de la seconde revue — 19 octobre 2026

Les quatre constats R1–R4 sont corrigés sur la base `3e17641d366321641be22ad968272a8e9e1ae198`. **133 tests réussis en 31,546 s**, dont seize nouveaux tests de régression. Aucune donnée métier, configuration ou affectation de planning actif modifiée ; aucune optimisation globale lancée.

## Modifications et résultats

| Constat | Correction | Vérification |
|---|---|---|
| R1 : filtres/coûts avant retrait des trajets | Préfiltrage horaire conservateur ; contrôle hard et coût des préférences sur les seuls créneaux effectivement occupés, après réservation des trajets. | Aller-retour généré librement malgré les deux interdictions sur les créneaux de trajet ; préférences positives/négatives sur ces créneaux sans effet sur le coût du même horaire ; présence positive imposée sur le trajet et interdiction de travail effectif toujours refusées. |
| R2 : remplacement tronqué/planning fixé réécrit | Remplacement représenté par ses créneaux exacts. Génération des sous-intervalles contigus dans la fenêtre -15/+30 minutes, y compris remplacement partiel ; conservation des activités des journées fixées et contrôle d'égalité des affectations à la sortie. | Marges couvertes en génération libre et fixée ; remplacement partiel accepté ; plusieurs remplacements fixés conservés ; dépassement de fenêtre refusé ; exception à l'interdiction de groupe maintenue pour les remplacements authentifiés. |
| R3 : fausses violations de coupure | Les métriques distinguent les coupures classiques des trajets minimaux, via le même helper que le validateur. Ajout de `travel_gaps_count` et `total_travel_gap_hours`. | Aller-retour : zéro coupure classique, zéro violation, deux trajets / 0,5 h. Une vraie pause supplémentaire reste signalée. Export HTML vérifié. |
| R4 : ancien quota affiché | Texte des règles exportées aligné sur la couverture perdue, sans quota par groupe source, avec fenêtre de remplacement autorisée. | Test du texte généré et export conservé dans ce dossier. |

Les préférences qui évitent les interruptions et changements de site restent en place. `scoring.py` et l'objectif compact n'ont pas été modifiés. Le THE et les heures enfants ne comprennent aucune heure de trajet nouvelle.

## Résidu supplémentaire du quota corrigé

Le test de remplacement partiel a découvert que `diagnose_the_capacity` utilisait encore un besoin artificiel de `nombre de groupes - 1` pendant les colloques. Pour un témoin de 1 h accepté par le validateur et le CP-SAT, il annonçait 1,50 h de besoin et bloquait les patrons avant génération.

- Preuve avant correction : `capacity-before.json`, avec données, planning, validation, CP-SAT et diagnostic contradictoire.
- Correction dans `solver.py` : le calcul préalable repose sur les besoins de groupe et de site effectivement définis. Les participants au colloque sont retirés de la couverture par les moteurs ; cela n'ajoute pas de besoin enfants.
- Vérification : absence de diagnostic d'insuffisance pour le cas valide, remplacement partiel généré librement/fixé ; une vraie demande supérieure à la capacité reste signalée.

Cette correction est nécessaire pour que la fenêtre de remplacement fonctionne dans les petits contrats ; aucune nouvelle règle métier n'a été inventée.

## Contrôles et traces

- `before-tests.txt` : douze tests initiaux avant correction, avec onze échecs d'assertion/sous-cas reproduits.
- `intermediate-tests.txt` : première suite complète, avec un seul échec dû au libellé du refus d'un trajet impossible. Le refus était maintenu ; son message historique a été rétabli.
- `all-tests.txt` : suite finale, **133/133**, 31,546 s.
- `tests/test_second_review_regressions.py` : seize tests ajoutés, incluant les cas conformes et les refus attendus. Les tests négatifs de présence exigent une réponse d'infaisabilité, pas seulement une absence de résultat.
- `validation.json` : empreintes finales des sources, empreintes inchangées des données/configuration/fixtures/sorties, métriques corrigées et résultat du diagnostic de capacité.
- `travel-result.json`, `travel-report.html`, `travel-report.csv` : exemple synthétique revalidé et exporté après correction. Aucun solveur global utilisé pour ces exports.
- Compilation des quatre modules modifiés et des nouveaux tests réussie ; contrôle Git des espaces effectué sur le code et la documentation. Les exports bruts conservent les fins de ligne et espaces émis par le générateur.

Reproduction de la suite :

```bash
python -m unittest discover -s tests -v
```

Environnement : Python 3.12.14, OR-Tools 9.15.6755, NumPy 2.5.4, SciPy 1.17.0. Pour reproduire dans cette copie locale : `PYTHONPATH=/workspace/scratch/8546a608cc32/deps`.

Les anciennes preuves et les assertions de comportements fautifs dans le dossier parent sont conservées comme historique ; ne pas utiliser leur succès comme critère de correction. Les tests ci-dessus expriment le comportement attendu actuel.

## Limites et prochaine action

L'élargissement de la fenêtre produit davantage de patrons. Un essai libre de contrôle comptable a atteint sa limite HiGHS ; ce résultat n'a pas été traité comme un bug métier. Les patrons aux affectations finales identiques sont désormais dédupliqués indépendamment de leurs segments bruts, en conservant le coût minimal. Le test comptable est fixé pour isoler les heures, tandis que les tests de trajet et remplacement continuent à exercer la génération libre.

Pas de nouvelle mesure de performance sur la semaine réelle ni de nouveau planning complet conforme. Pas de test Windows ou graphique interactif. Les patrons libres restent un domaine de recherche limité : un remplacement contigu optionnel par patron ; les journées fixées conservent plusieurs remplacements. Les refus explicites antérieurs pour plusieurs colloques par groupe et certaines options THE restent applicables. Aucune équivalence exhaustive avec CP-SAT revendiquée.

**Prochaine action utile :** reprendre, si demandé, la réparation ciblée des cinq créneaux de couverture connus avec ces corrections, avant une nouvelle optimisation globale longue. Le présent lot ne relance pas cette recherche.
