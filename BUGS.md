# Bugs et risques connus

## Ouverts

### Aucun planning strict actuel confirme

Statut : ouvert, priorite haute.

Le planning assoupli est reproductible et valide hors limite de jours, mais aucun planning avec toutes les limites de jours n'est encore confirme.

Le meilleur diagnostic optimal observe respecte maintenant la limite de Valerie. Les depassements restants sont A repourvoir, Natacha et Anais.

### Modele encore volumineux

Statut : ouvert, priorite haute.

Les modeles complets peuvent encore depasser 500 000 patrons et plusieurs gigaoctets. Un appel natif HiGHS trop volumineux peut depasser son budget ou faire tomber `python.exe`.

Les sous-modeles compacts de 150 000 a environ 330 000 patrons terminent proprement. Le modele complet a 15 minutes reste trop lent.

Piste actuelle : produire un candidat avec le moteur temporel compact, puis le verifier avec le validateur complet et le reparer localement si necessaire.

### Dernier planning valide trompeur

Statut : ouvert, priorite haute.

`outputs/planning_gwendo_latest.json` a `status: ok`, mais provient d'un calcul ou la limite de jours a ete assouplie. Le chargeur peut l'utiliser comme indication de groupes principaux.

Risque : une affectation principale ancienne peut masquer une meilleure combinaison ou rendre la recherche stricte impossible. Si le modele prouve `Infeasible`, tester d'abord cette hypothese avant de modifier les regles metier.

### Timeout natif imparfait

Statut : ouvert, priorite haute.

Le budget est transmis a HiGHS et l'interface peut tuer l'arbre de processus. Cependant certains gros appels natifs ont depasse le budget avant de rendre la main. Ne pas confondre cet arret anormal avec une absence de solution.

### Equivalence des moteurs historiques non garantie

Statut : connu, non prioritaire.

Les chemins `scipy` et `ortools` sont historiques. Ils ne sont pas garantis equivalents a `pattern_mip` pour le THE, les colloques, les remplacements et toutes les regles recentes.

Ils peuvent etre audites comme generateurs de candidat, mais aucun candidat ne doit etre accepte sans `verify_solution`.

## Corriges

### Memoire des patrons et de la matrice

Statut : fortement corrige dans le repertoire de travail.

La matrice utilise des buffers compacts et un CSR direct. Les signatures geantes, metadonnees Python par patron et index de couverture en listes ont ete remplaces par des tableaux compacts. Les modeles moyens atteignent HiGHS sans `MemoryError`.

### Recherche progressive et repli des groupes

Statut : corrige.

Le solveur sait maintenant conserver un candidat valide, liberer progressivement les groupes principaux et elargir les patrons. Les essais continus inutiles ont ete remplaces par une recherche avec coupures.

### Faux controle d'un site unique par jour

Statut : corrige.

Le changement de site est autorise entre deux blocs d'une journee coupee. Le controle hard porte sur le changement de groupe ordinaire dans une meme demi-journee. Les remplacements de colloque restent des exceptions.

### Ecrasement du dernier planning valide

Statut : corrige.

Les fichiers `latest` ne sont remplaces que par un planning dont les controles hard finaux sont sans erreur.

### `tolerance_slots` non defini dans CP-SAT

Statut : corrige par `faa225f`.

Le chemin CP-SAT ne plante plus sur cette variable, mais reste un moteur historique.

### Diagnostic des patrons insuffisant

Statut : corrige par `faa225f`.

Le journal et les resultats distinguent patrons continus, coupes, mixtes et variantes de remplacement.
