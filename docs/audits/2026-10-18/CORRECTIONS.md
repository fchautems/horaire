# Corrections de l’audit — 18 octobre 2026

Base : `b036113`. Ce document donne l’état après correction ; le rapport d’audit et ses résultats restent les preuves historiques de la version antérieure. Ses sondes caractérisent volontairement les anciens défauts et ne constituent pas la suite de régression courante.

## État par constat

| ID | Traitement et contrôle |
|---|---|
| A01 | Affectations ordinaires dans un groupe interdit refusées dans le validateur, le compact et les coûts des patrons. Les règles positives restent des règles de groupe principal. L’exception de remplacement reste soumise à Q03. |
| A02 | Toute identité supplémentaire dans le planning est rejetée avant de compter la couverture. |
| A03 | Colloques et remplacements doivent correspondre à une réunion réelle, au groupe et au jour attendus. La fenêtre de remplacement existante -15/+30 minutes est conservée, sans validation nouvelle de cette convention. |
| A04 | Groupes principaux absents reconstruits depuis les règles hard positives puis les heures ; contrôles de colloques toujours exécutés. Absence de groupe impossible à reconstruire signalée pour les participants. Métadonnées mal formées refusées. |
| A05 | Validation indépendante et comparaison au planning protégé dans la sortie commune à tous les moteurs. Un candidat invalide ou moins bon ne remplace pas la référence. |
| A06 | Schéma des blocs et métadonnées du cache vérifié avant calcul ou inférence. Les caches mal formés sont invalides au lieu de lever une erreur de clé. |
| A07 | Les coupures ne sont plus ancrées à midi ; placement du premier segment sur toute la grille, segments d’un créneau autorisés dans le domaine non restreint. Le cas matinal 08–09 / 10–11 passe. Les domaines volontairement restreints restent des recherches partielles ; aucune équivalence exhaustive des moteurs n’est revendiquée. |
| A08 | Suppression de l’obligation d’un remplaçant de chaque groupe source. Les contraintes de couverture déterminent les besoins de remplacement. Le microcas sans besoin pendant le colloque passe dans les deux moteurs. |
| A09 | Réserve du repli portée à 30 % du budget, seuil de tentative abaissé à une seconde ; simulation de 100 secondes confirmant l’appel aux patrons. Leur préparation native conserve son propre budget minimum. |
| A10 | Durée des coupures et manque d’heures dans les petites journées ajoutés à l’objectif compact et à l’évaluation indépendante commune. Aucun raccourcissement de coupure n’est affirmé sans nouvelle recherche. |
| A11 | Poids horaires/groupes soft, jours et priorité temps partiels, groupe/site principal, durée des coupures et courtes journées transmis au compact et au score. Interrupteurs de compaction/stabilité appliqués aux poids. Gap d’optimisation transmis. Une ou deux périodes supportées ; autre maximum rejeté explicitement. Les options historiques structured/smooth/fast_feasible font l’objet d’un avertissement explicite au lieu de prétendre piloter le compact. |
| A12 | Tous les colloques contrôlés dans le validateur et représentés dans le compact. Le moteur par patrons refuse explicitement plusieurs colloques par groupe : prise en charge complète limitée au compact, aucun écrasement silencieux. |
| A13 | Plusieurs groupes en colloque sur un même créneau conservés dans un ensemble ; présence et reconstruction du planning tiennent compte du groupe principal. Le microcas simultané passe. |
| A14 | Identités, jours, groupe/site, horizon et alignement à quinze minutes des blocs vérifiés, y compris avant fixation d’un planning dans CP-SAT. |
| A15 | Durées et valeurs numériques non finies refusées. Le lecteur JSON partagé refuse NaN/Infinity ; l’écriture refuse les nombres non finis. |
| A16 | Budget THE visible contrôlé ; comptabilité des options de colloque alignée dans compact/validateur. Les options non standard non prises en charge par les patrons sont refusées avec orientation vers le compact. La règle des très petits contrats n’a pas été assouplie : la réunion ne peut pas dépasser le budget THE dans le mode courant. |
| A17 | Alias transmis au validateur par les bundles du compact/des patrons et par la revalidation du lanceur. Microcas qualification accepté de bout en bout. |
| A18 | Plafonds explicites par groupe et par site appliqués dans compact, patrons et validateur. Hors plafond explicite, conservation du plafond historique max(3, besoin). |
| A19 | **Clarifié par Frédéric le 18 octobre 2026.** Une éducatrice peut travailler avant l’ouverture ou après la fermeture pour préparer ou ranger. Les horaires propres au site ne doivent pas interdire cette présence : aucune nouvelle contrainte hard ajoutée. Le constat est clos par décision métier ; ce comportement n’est pas un bug. L’horizon global de calcul reste inchangé. |
| A20 | Un jour inconnu provoque une erreur explicite ; il ne devient plus une demande sur tous les jours après un aller-retour éditeur. |
| A21 | Le bouton « dernier planning » revalide les candidats et privilégie le fichier latest configuré. |
| A22 | Les callbacks différés capturent le texte de l’exception avant la sortie du bloc except. |
| A23 | Plafond absolu nul accepté par le rapport ; les règles désactivées de plafond/THE/jours ne sont plus affichées comme actives. |
| A24 | OR-Tools >=9.15,<10 ajouté aux dépendances. |
| A25 | Indice du jour transmis depuis l’enregistrement de la tâche dans le repli du lissage historique. |
| A26 | Un statut ok sans listes explicites errors et hard_errors ne certifie plus un résultat. |
| A27 | Classement indicatif borné à 512 combinaisons, sans restreindre les affectations du modèle. Chronomètre démarré avant construction ; temps consommé déduit du budget de recherche. Les appels natifs peuvent encore dépasser légèrement leur échéance. |

## Robustesse et limites

- R01 : JSON, CSV et HTML écrits chacun par fichier temporaire et remplacement atomique. Injection d’échec de remplacement JSON : ancienne version conservée. Ce n’est pas une transaction atomique commune aux trois fichiers : le JSON validé reste l’autorité de reprise ; des exports peuvent différer après une interruption entre deux remplacements.
- R02 : chaque amélioration intermédiaire de la phase d’optimisation est reconstruite et validée avant appel du checkpoint. Le lanceur ne conserve que les candidats conformes à sa politique courante. L’objectif d’un candidat est évalué sur l’expression originale du modèle et ses valeurs ; la valeur scalaire brute de CP-SAT est conservée séparément pour diagnostic. Un écart a été observé sur un candidat intermédiaire ; le score des affectations et l’expression du modèle concordent dans la régression de recherche libre.
- R03 : échéance vérifiée avant traitement de chaque ligne, file de logs bornée à 2048 éléments, historique texte borné à 4000 lignes ; aucun test graphique réel sous Windows.
- R04 : validation structurelle partagée avant construction et validation des résultats, protection des nombres, noms dupliqués, références, règles, effectifs et plages. Cela ne constitue pas une preuve contre tous les fichiers arbitraires ni un schéma réglementaire exhaustif.
- R05 : les fichiers de reprise de juin portent désormais un avertissement historique et renvoient vers cet état et PROJECT_STATE.md.

Les conventions Q01 (présence dans une fenêtre), Q02 (pourcentages cumulés), Q03 (fenêtre de remplacement et interdictions pendant celui-ci) et Q04 (pauses, repos, déplacements) restent celles de l’audit. Aucun nouveau choix métier ou réglementaire n’a été déduit du feu vert donné pour corriger les défauts techniques.

## Vérifications

La suite de production comprend les tests existants et les régressions de l’audit dans `tests/test_audit_regressions.py`, plus les contrôles de politique dans `test_quality_alignment.py`. Les anciens tests contenant un faux colloque ou un planning simulé incomplet ont reçu des données cohérentes ; leurs assertions de continuité et de conservation sont préservées.

Le candidat de l’essai global du 17 octobre est revalidé sans erreur puis reproduit à affectations fixées. Sa politique historique donne toujours **626975**. Avec les mêmes paramètres expérimentaux et le terme de coupure désormais actif, il donne **646975**, dont 20000 pour la durée des coupures ; objectif du modèle et calcul indépendant concordent. Les affectations et le planning actif ne sont pas modifiés. Une reproduction fixe ne prouve aucune optimalité globale.

Résultat final : **93 tests réussis en 11.428 secondes** ; compilation des modules et git diff --check réussis. Journal : [corrections-tests.log](corrections-tests.log) ; synthèse : [corrections-validation.json](corrections-validation.json). Les limites de publication sont consignées dans PROJECT_STATE.md. Pas de nouvelle optimisation globale, ni de validation Windows ou graphique réelle, ni de garantie d’absence d’autres bugs.


## Décisions complémentaires — 18 octobre 2026

Q02 confirmé : pourcentages sur la semaine. Q03 confirmé : fenêtre de remplacement -15/+30 minutes, tout remplaçant admissible sous les autres contraintes, interdictions de groupe non applicables pendant le remplacement. Q04 précisé : aucun repos minimum entre deux jours dans le modèle, dix minutes de déplacement entre sites. Les pauses dans une journée restent à définir ; Q01 reste ouvert. La contrainte des dix minutes est nouvellement spécifiée et n’est pas encore implémentée ni couverte par les 93 tests du lot ci-dessus. Aucun nouveau code ou planning modifié lors de cet enregistrement.
