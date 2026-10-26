# Bilan de l'année

La page `/bilan` (`retro.py`, `web/api/retro.py`) raconte une année en une douzaine de
constats, une carte chacun. Elle s'ouvre sur la dernière année entière ; une année du
relevé couvrant au moins trois mois se choisit (marquée « * » si elle est incomplète).

- **Les trois chiffres** : encaissé (salaires et autres revenus, sans les parts remboursées
  par des amis), dépensé (sans les virements d'épargne), gardé et sa part de l'encaissé.
  Contre l'année d'avant **mois pour mois** quand l'une des deux est incomplète : sinon
  cinq mois d'une année contre douze de la suivante diraient +150 %.
- **Le mois le plus cher et pourquoi** : la catégorie la plus au-dessus de son mois
  ordinaire de l'année (la médiane des autres mois), et le plus léger.
- **Où est parti l'argent**, les six premières catégories ; **en hausse, en baisse** contre
  l'année d'avant.
- **L'habitude** (le commerce le plus fréquenté par carte), **là où l'on a laissé le plus**
  (parmi ce qui se choisit à la caisse : restaurants, courses, shopping, loisirs, pas les
  factures), **la plus grosse dépense**, **les nouveaux noms** (bénéficiaires jamais payés
  les années d'avant).
- **Ailleurs** : les jours de paiement **sur place** par pays (repas, hôtel, courses : un
  site qui facture depuis l'étranger n'est pas une visite, `projects.ON_SITE`), et les
  voyages tels que `/projets` les reconnaît.
- **La plus longue pause** sans un paiement par carte, et le jour de la semaine où la carte
  sort le plus.

Tout est calculé dans `retro.review` ; la page ne fait que mettre en cartes.

## La navigation, repliée (19.10)

Avec À venir, Projets, Impôts et Bilan, la barre latérale comptait onze entrées et
écrasait « Sur cette page » à quelques lignes. Les pages ouvertes de temps en temps
(Projets, Impôts, Bilan, Corrections, Assistant : `more` dans `shell/nav.ts`) sont
repliées sous « Plus », ouvert d'office quand la page courante en fait partie et sinon
selon le dernier choix (`localStorage`). Les lignes sont plus serrées ; relevé attendu
et sauvegarde tiennent sur une ligne chacun (la carte « À faire » du tableau de bord les
détaille), Importer, le thème et la relecture partagent une rangée.
