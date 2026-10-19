# Interruptions de déplacement autorisées — 19 octobre 2026

Frédéric confirme que les interruptions nécessaires aux déplacements doivent être autorisées. Elles ne consomment plus une coupure classique pour la limite de périodes par jour.

- Minimum intersites conservé : dix minutes, soit un créneau libre de quinze minutes sur la grille actuelle.
- Seule cette interruption minimale bénéficie de l'exception. Une pause plus longue ou sur le même site reste une coupure classique, soumise aux limites existantes.
- Le validateur et le compact CP-SAT comptent les périodes en réunissant uniquement les plages séparées par un trajet minimal entre sites. Le contrôle de durée des pauses fait la même distinction.
- Les patrons conservent au plus deux périodes ordinaires et réservent les créneaux de déplacement autour des changements de site, y compris pour les remplacements ; leurs couvertures, durées et exports excluent ces créneaux. Les jours fixés avec un aller-retour peuvent être représentés.
- Les heures contractuelles et la politique de score existante sont conservées : aucun temps de couverture, de colloque ou nouvelle heure contractuelle n'est ajouté pendant un trajet. Les pénalités soft continuent de décourager les interruptions et déplacements lorsque ceux-ci sont évitables.
- Maximum d'une ou deux périodes ordinaires supporté comme auparavant. L'option de trois périodes ordinaires reste refusée explicitement par le compact. Les limites antérieures des patrons (notamment options THE et colloques multiples par groupe) restent explicites ; aucune équivalence exhaustive des domaines ni mesure de performance sur la semaine réelle n'est revendiquée.

## Vérification

**117 tests réussis en 14,057 secondes**, dont quatorze nouveaux cas. Compilation et `git diff --check` réussis.

Les nouveaux cas couvrent un aller-retour dans une seule période ordinaire, une vraie pause ajoutée, deux vraies pauses refusées, les longues interruptions, les changements de groupe sur le même site, le délai minimum de trajet, le seuil par grille, les déplacements autour d'un colloque visible, l'interdiction de compter les trajets comme couverture enfants, les pauses classiques désactivées et les patrons fixés/générés.

Le cas isolé qui bloquait est donc autorisé. Revalidation de la semaine historique après ajout des sept délais : les trois erreurs de nombre de périodes disparaissent ; il reste exactement cinq créneaux en sous-effectif (voir `validation.json`). Ce planning n'est pas déclaré valide et aucun planning actif n'est remplacé. Aucun nouveau calcul global n'a été lancé.

`tests.txt` contient le résultat de la suite complète ; `validation.json` contient les empreintes et les erreurs restantes. Le diagnostic historique conserve les résultats observés sous la règle précédente et n'est pas réécrit.
