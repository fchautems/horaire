# Seconde revue indépendante — 19 octobre 2026

## Conclusion

Revue de **`748acbb3a4c96250f8659bc7683a0222a78072f2`**, tête de `main` vérifiée sur GitHub au début et avant publication. Cette version comprend l'autorisation des interruptions minimales de trajet. **Quatre constats confirmés**, dont deux défauts fonctionnels du moteur par patrons et deux défauts de restitution. Aucune correction de production effectuée.

Les **117 tests existants passent en 13,369 s**. Les diagnostics nouveaux sont construits indépendamment des helpers de l'audit précédent, avec des données synthétiques. Les assertions du script caractérisent les anomalies présentes : leur réussite ne signifie pas que ces anomalies sont corrigées.

| Identifiant | Priorité | Constat confirmé |
|---|---|---|
| R1 | Haute | Les patrons appliquent les règles horaires et leurs coûts avant de retirer les trajets : exclusion d'un horaire réalisable et pénalités sur des créneaux vides. |
| R2 | Haute | La fenêtre de remplacement autorisée n'est pas représentée complètement ; un planning fixé peut être modifié silencieusement. |
| R3 | Moyenne | Le bilan qualité annonce des violations de coupure pour des trajets expressément exemptés. |
| R4 | Faible | Le résumé des règles exporté réintroduit textuellement l'ancien quota de remplaçants par groupe source. |

Ces résultats **ne démontrent pas la cause des anciens UNKNOWN**, ni l'infaisabilité ou la faisabilité de la semaine réelle. Aucun calcul global nouveau, aucune modification de planning actif.

## Version, périmètre et méthode

Lecture initiale de `PROJECT_STATE.md`, puis `docs/REGLES_METIER.md`, du suivi des corrections A01–A27 et du diff du dernier commit. Aucun `AGENTS.md` ni `MODEL_GUIDE.md` trouvé dans le dépôt et les emplacements `/workspace` inspectés. Aucun outil Brain disponible identifié.

Sources examinées : `domain.py`, validateur et CP-SAT compact dans `solver.py`, `pattern_mip.py`, `scoring.py`, `quality.py`, `reports.py`, ainsi que les tests associés. Les chemins historiques et l'interface ne font pas l'objet d'un nouvel audit exhaustif.

- Python 3.12.14, OR-Tools 9.15.6755 ; versions NumPy/SciPy et empreintes dans `environment.json`.
- Dépendances installées hors du dépôt ; `requirements.txt` inchangé.
- 29 appels de micro-résolution dans le diagnostic final : CP-SAT à planning fixé (budget individuel 3 s), patrons à domaine complet par défaut, libres ou fixés (budget individuel 12 s).
- L'ensemble du diagnostic final prend environ **7,4 s**, hors suite existante. Les budgets ne sont pas des temps consommés.
- Aucun statut UNKNOWN utilisé comme preuve. Les exclusions discutées ci-dessous sont appuyées par un horaire témoin accepté, des témoins comparatifs et la localisation du filtre fautif.
- Les empreintes avant/après des sources, données, configuration, fixtures et sorties suivies sont identiques. Seuls ce dossier documentaire et `PROJECT_STATE.md` sont ajoutés/modifiés.

## R1 — Traitement horaire antérieur au retrait des trajets

**Attendu et justification.** Règles hard 3 et 13 : la présence effective doit respecter les plages horaires ; les trajets réservés ne sont ni couverture ni heures contractuelles. Le compact et le validateur appliquent les règles horaires aux affectations visibles. Un patron dont ces affectations respectent les interdictions doit donc rester disponible. Une préférence négative respectée ne doit pas ajouter une pénalité de présence.

**Cas minimal reproductible.** Une personne, lundi uniquement, groupe principal A, sans colloque personnel, contrat 2,5 h et THE à 0 %. Deux sites. Un colloque B réel de 13:15 à 14:00. Couverture demandée exactement sur les trois plages suivantes ; aucune demande pendant les trajets.

| Plage | Affectation | Heures |
|---|---|---:|
| 11:45–13:00 | A / bas, enfants | 1,25 |
| 13:00–13:15 | Trajet, aucune affectation | 0 |
| 13:15–14:00 | B / haut, remplacement de colloque | 0,75 |
| 14:00–14:15 | Trajet, aucune affectation | 0 |
| 14:15–14:45 | A / bas, enfants | 0,5 |

**Résultat exécuté** (`results.json → travel_prefilter`). On ajoute des interdictions horaires hard seulement sur les créneaux vides :

| Interdiction | Validateur | CP-SAT fixé | Patrons libres | Patrons fixés au témoin |
|---|---|---|---|---|
| Aucune | 0 erreur | OPTIMAL, valide | Optimal, valide | Optimal, valide |
| Aller seulement | 0 erreur | OPTIMAL, valide | Optimal, valide | Optimal, valide |
| Retour seulement | 0 erreur | OPTIMAL, valide | Optimal, valide | Optimal, valide |
| Aller et retour | 0 erreur | OPTIMAL, valide | **HiGHS Infeasible** | **Optimal, valide** |

Les patrons libres génèrent 542 candidats pour le dernier cas, mais excluent le témoin. Ce n'est pas un simple conflit entre règles : **le même moteur l'accepte lorsqu'il reçoit le planning fixé**.

**Coûts reproduits** (`travel_soft_cost`). En remplaçant les deux interdictions par des préférences négatives soft, le planning produit reste strictement identique et les deux préférences sont respectées. Pourtant l'objectif interne des patrons passe de **72000 à 72090**. Le CP-SAT reste à **36810**, et le bilan rapporte zéro présence dans ces fenêtres. Avec un poids 1000, les patrons obtiennent 129400 pour le même horaire. Les valeurs absolues des objectifs de moteurs différents ne sont pas comparées : c'est la variation injustifiée au sein des patrons qui constitue la preuve.

**Localisation et cause.** `src/creche_planning/pattern_mip.py`, `work_cost_or_none` vers 577–600, appels de génération vers 1140–1370, puis `add_pattern` vers 737–780. Le masque de travail et les coûts sont évalués sur les segments bruts ; les créneaux de trajet sont retirés ensuite. Le nouveau contrôle après retrait ne peut restaurer un patron déjà éliminé. Les coûts ne sont pas recalculés sur la présence finale. Deux trous de trajet exigent trois segments bruts, alors que le générateur n'en énumère que deux ; la nouvelle exception devait précisément les fusionner logiquement.

**Impact.** Faux échec de recherche des patrons, domaine incomplet et classement soft erroné. Impact sur une recherche globale réelle non mesuré ; le compact passe les témoins.

**Correction proposée.** Réserver les trajets avant l'évaluation définitive des règles horaires et des préférences. Rendre les filtres préalables conservateurs, puis calculer les coûts sur les affectations finales. Conserver les pénalités voulues pour les interruptions et les changements de site ; ne pas compter une préférence horaire comme violée pendant un créneau sans présence. Ajouter les témoins aller seul, retour seul, aller-retour et préférences soft.

## R2 — Fenêtre de remplacement tronquée et planning fixé réécrit

**Attendu et justification.** Décision métier du 18 octobre, règle 12 et précisions de `REGLES_METIER.md` : remplacement autorisé quinze minutes avant et trente minutes après le colloque. Le nom et l'usage de `fixed_daily_schedules`, ainsi que le test existant de préservation des trajets fixés, exigent la conservation des affectations fixées ; une forme non prise en charge doit être refusée explicitement.

**Cas minimal.** Une personne, groupes A et B sur le même site pour éliminer les déplacements, contrat 2 h, THE à 0 %, principal A. Colloque B lundi 13:15–14:00. Planning fixé : A 12:45–13:00, remplacement B **13:00–14:30**, A 14:30–14:45.

**Résultat exécuté** (`replacement_window`).

- Sans besoin de couverture imposé : validateur sans erreur, CP-SAT fixé valide ; patrons fixés renvoient `status=ok`, **mais déplacent les affectations** : A 12:45–13:15, B 13:15–14:00, A 14:00–14:45. La personne conserve ses heures, mais **45 minutes de remplacement B deviennent du travail A**.
- Avec une couverture minimale exactement égale aux affectations du témoin : validateur sans erreur et CP-SAT fixé OPTIMAL ; patrons libres **et fixés** terminent HiGHS Infeasible.

**Localisation et cause.** `pattern_mip.py`, `add_pattern` vers 706–734, `replacement_options` vers 922–939 et `add_fixed_day_pattern` vers 941–1029. La génération et la reconstruction des remplacements utilisent uniquement `colloque['slots']`. Le chemin fixé mémorise la cible du remplacement, puis reconstruit sa durée à partir du colloque, perdant les bornes du bloc fourni.

**Impact.** Réparation guidée susceptible de modifier des affectations censées être conservées ; impossibilité artificielle de couvrir les marges autorisées. La validation finale peut accepter l'horaire modifié s'il n'existe pas de demande de couverture discriminante. Les données ou plannings réels n'ont pas été modifiés pendant la revue.

**Correction proposée.** Représenter explicitement les créneaux des remplacements sur la fenêtre autorisée, y compris leurs bornes et les cas partiels permis. Préserver exactement les activités/groupes/horaires des jours fixés, ou renvoyer une limite de support explicite. Vérifier leur égalité sémantique à la sortie. Ne pas réintroduire de quota de remplaçants.

## R3 — Faux dépassement de coupure dans le bilan qualité

**Attendu et justification.** Règle 13 : les deux trajets minimaux de l'aller-retour ne consomment pas de coupure classique. Avec `max_split_gap_minutes=0`, ils restent permis. Une pénalisation soft des interruptions est expressément conservée : son existence n'est pas un bug.

**Cas et résultat exécutés** (`travel_report`). Reprendre l'aller-retour R1 avec cette limite de zéro : CP-SAT OPTIMAL, `checks.errors=[]`, `hard_error_count=0`, mais le bilan retourne **`split_gap_violations=2`**. La ligne « Coupures » de l'export HTML est « A surveiller », alors que les deux seuls intervalles vides sont des trajets exemptés. `travel-report.html` conserve la preuve ; le CSV conserve les trois activités et aucune activité fictive de trajet.

**Localisation.** `src/creche_planning/quality.py`, `build_quality_summary` vers 290–302 et 365–412 ; restitution dans `reports.py` vers 343–355. Tous les trous positifs sont ajoutés à `split_gaps`, sans `is_short_site_transfer`.

**Impact.** Faux signal de non-conformité dans les indicateurs/export ; **pas de rejet hard par le validateur** et pas de divergence observée du score compact : objectif et score recalculé valent tous deux 36810.

**Correction proposée.** Séparer interruptions visibles, trajets et coupures classiques dans les métriques ; appliquer l'exemption au compteur des violations. Conserver les préférences soft prévues. Ne pas supprimer globalement la pénalisation des trajets.

## R4 — Ancien quota de remplacement encore présenté comme règle hard

**Attendu et justification.** Règle 12 : remplacement selon la couverture effectivement perdue ; aucun quota d'une personne issue de chaque autre groupe. Le résumé utilisateur doit refléter cette règle déjà corrigée dans les moteurs.

**Cas minimal et résultat exécuté.** Appeler `reports.build_rule_summary` sur les données du microcas, puis exporter le résultat via `write_html`. Le texte hard « colloques » contient encore : **« une personne de chaque autre groupe remplace »**. Preuve : `results.json → travel_report.rule_summary` et `travel-report.html`. Le test existant `test_no_unnecessary_replacements_by_source_group` passe : les moteurs ne demandent plus ce quota.

**Localisation.** `src/creche_planning/reports.py`, `build_rule_summary`, lignes 88–95 ; cette structure est attachée aux résultats par `solver.py` et exportée.

**Impact.** Documentation générée contradictoire, pouvant conduire l'utilisateur à diagnostiquer à tort un défaut de remplacement. Aucun quota erroné nouvellement démontré dans le modèle.

**Correction proposée.** Remplacer ce texte par la règle de couverture perdue et rappeler la fenêtre autorisée ainsi que l'absence de couverture pendant les déplacements. Tester le résumé généré, pas seulement la documentation Markdown.

## Contrôles conformes, hypothèses et limites

**Contrôles exécutés sans nouvelle anomalie :**

- Avec 3,25 h contractuelles, 25 % de THE arrondi à 0,75 h, l'aller-retour donne **2,5 h enfants + 0,75 h THE invisible = 3,25 h** dans le validateur, CP-SAT et patrons libres/fixés. Les 30 minutes de trajet n'ajoutent aucune heure.
- Une demande d'enfants ajoutée pendant le trajet est rejetée : erreur de couverture à 13:00 dans le validateur, INFEASIBLE pour le CP-SAT fixé ; refus préalable de capacité enfants pour les patrons. Ce refus de capacité est attendu dans ce témoin, pas un bug.
- Le score compact reste égal au score recalculé, y compris en présence de trajets et de préférences horaires entièrement respectées.
- Les tests existants couvrant vrais trous, trajets insuffisants, un aller-retour plus une coupure, colloques multiples/simultanés, qualification, cache et protections de sortie passent dans la suite des 117 tests.

**Hypothèses non reproduites :** double comptage des trajets dans les heures, couverture fantôme pendant les trajets, divergence du score compact provoquée par le nouveau comptage des périodes. Ces témoins ne prouvent pas l'absence de défaut sur toute combinaison possible. Aucun lien causal établi entre R1/R2 et les recherches globales UNKNOWN précédentes.

**Limites techniques :** patrons à plusieurs colloques par groupe ou options THE non prises en charge restent explicitement refusés ; ces refus documentés ne sont pas de nouveaux bugs. Le domaine complet par défaut des patrons reste distinct d'une preuve d'équivalence générale avec CP-SAT. Pas d'exécution Windows, de test graphique interactif, ni de mesure globale de performance. HTML contrôlé par son contenu généré, sans validation visuelle dans un navigateur. L'atomicité commune JSON/CSV/HTML n'a pas été réauditée.

**Questions métier :** aucune nouvelle décision n'est nécessaire pour corriger R1–R4 selon les règles écrites. Une éventuelle volonté d'interdire aussi les déplacements durant une indisponibilité horaire serait une règle supplémentaire à préciser : actuellement le compact et le validateur contrôlent la présence visible. La rémunération juridique du trajet, les pauses réglementaires et les repos relèvent d'un autre périmètre ; aucune règle n'en a été déduite ici.

## Reproduction et preuves

Depuis la racine du dépôt, avec les dépendances installées :

```bash
python -m unittest discover -s tests -v
python docs/audits/2026-10-19-second-review/probes.py
```

Dans l'environnement de cette revue, préfixer les commandes avec `PYTHONPATH=/workspace/scratch/8546a608cc32/deps`.

- `probes.py` : cas synthétiques, comparaisons et assertions des comportements observés.
- `results.json` : entrées complètes, témoins, statuts, plannings, contrôles, scores et durées.
- `probes.log` : résultat de l'exécution finale.
- `baseline-tests.txt` : suite existante.
- `environment.json` : version auditée, dépendances, budgets et empreintes avant/après.
- `travel-report.html`, `travel-report.csv` : exports réellement générés sur un cas synthétique.

**Prochaine action utile :** corriger R1 et R2 avec les témoins conservés, puis les indicateurs/textes R3–R4. Rejouer ces cas et la suite existante avant toute nouvelle optimisation globale. Les sources de production restent inchangées dans cette livraison.
