# À venir

La page `/a-venir` (`upcoming.py`, `health.py`, `web/api/upcoming.py`) regarde devant :
ce que les engagements déjà payés vont prélever, quand, ce qu'ils pèsent par an, de
combien leur prix a bougé, et jusqu'à quand on peut encore les changer. Le tableau de
bord en reprend les cinq prochaines échéances du mois (panneau « À venir ») et met un
délai proche dans sa carte « À faire ».

## Un engagement est lu, jamais saisi

Rien ne se déclare : un engagement est un bénéficiaire payé **à rythme et à montant
réguliers** (`upcoming.commitments`).

- **Le rythme** est l'écart médian entre deux paiements, entre 20 et 400 jours. En
  dessous, c'est une habitude (la cantine) ; au-dessus, il n'y a plus de rythme à lire.
  Les écarts doivent concorder (déviation médiane ≤ 25 % de l'écart, 10 % pour un
  paiement annuel) et les montants tenir (coefficient de variation ≤ 0.6 : l'électricité
  varie dans cette marge, un restaurant non).
- **Trois paiements** établissent un rythme ; deux suffisent pour un paiement annuel
  d'au moins 50 CHF. Attendre une troisième année pour annoncer l'assurance ménage ne
  servirait à rien.
- **Une carte n'engage pas**, sauf un abonnement : un paiement par carte n'est un
  engagement que s'il est classé dans « Télécom & abonnements ». La pharmacie deux
  fois par an, la station-service chaque été et la cantine passaient sinon pour des
  contrats.
- **Ce qui se choisit à chaque fois n'en est jamais un** : restaurants, alimentation,
  shopping, loisirs (`upcoming.CHOSEN`), quel que soit le moyen de paiement. Sur le
  vrai relevé, un restaurant fréquenté chaque mois s'affichait en engagement (19.10).
- **Toujours actif** : silencieux depuis plus d'une fois et demie son rythme (plus une
  semaine), l'engagement est fini ou en retard. Le panneau « Engagements sans passage
  récent » du tableau de bord le dit ; ici, il n'est pas annoncé.
- Les Twint non identifiés, les virements à des personnes et le non classé ne sont pas
  des engagements, quel que soit leur rythme.

**L'activité se juge à la fin du relevé, l'échéance depuis aujourd'hui.** Un relevé
vieux de trois semaines ferait sinon taire toutes les factures. Une échéance entre la
fin du relevé et aujourd'hui est gardée, marquée « probablement passée » et repliée :
elle est sans doute payée, l'export ne le montre pas encore. Elle n'entre pas dans les
totaux.

**Une date suit le jour habituel.** Un loyer payé le 1er tombe le 1er, pas 30.44 jours
plus tard ; un paiement du 31 tombe le 30 en novembre et revient au 31 en décembre. Le
pas se compte en mois dès que le rythme est d'au moins quatre semaines.

**Le montant annoncé** est la médiane des trois derniers paiements (le dernier pour un
paiement annuel), marqué « ≈ » quand il varie. Le coût annuel en découle : 12 fois le
montant mensuel, pas 365.25 / 30.44 fois, qui donnait 11'999 CHF pour un loyer de 1'000.

**Une hausse se mesure contre le paiement d'il y a un an**, ou contre le premier quand
l'historique est plus court ; elle n'est cherchée que sur un prix fixe (les trois
derniers paiements identiques), pas sur une facture qui varie. La date « depuis » est le
premier paiement au nouveau prix.

Les revenus réguliers (un rythme mensuel, hors remboursements) donnent la date du
salaire, pour lire le mois qui vient contre ce qui le couvre. La page ne projette pas la
dépense courante : c'est le travail de `/previsions`.

## Les délais

- **La caisse maladie** se change pour le 1er janvier par une résiliation **reçue** au
  plus tard le 30 novembre (LAMal art. 7) : date de la loi, sûre. Elle s'affiche avec la
  hausse de la prime sur un an. Une franchise plus basse se demande aussi avant le
  30 novembre, une plus haute jusqu'au 31 décembre.
- **Une assurance annuelle** (« Autres assurances ») se résilie d'habitude trois mois
  avant son échéance, prise comme la date du prochain prélèvement. C'est un usage, pas
  une loi : la ligne porte « à vérifier ».

Un délai à 45 jours ou moins entre dans la carte « À faire » du tableau de bord.

## La franchise rejouée

`health.py` répond à « quelle franchise m'aurait coûté le moins ? » avec ce que la loi
fixe :

- **à charge de l'assuré** : la franchise, puis 10 % du reste, plafonnés à 700 CHF par an ;
- **le rabais de prime** d'une franchise plus haute est au plus 70 % du risque
  supplémentaire (OAMal art. 95). Les primes des autres franchises sont déduites de
  celle que l'on paie en supposant ce rabais maximal. Beaucoup de caisses l'accordent,
  pas toutes ; la page le dit et renvoie à priminfo.admin.ch pour les primes exactes.

**Les frais de santé d'une année sont lus à l'envers.** Le relevé ne voit pas la facture
totale : sous le tiers payant, la caisse paie la pharmacie directement. Il voit en
revanche la part de l'assuré : ce qu'il a payé aux soignants, plus ce que la caisse lui
refacture au-delà de la prime (tout débit de la caisse qui n'est pas le montant le plus
fréquent de l'année), moins ce qu'elle lui a remboursé. Cette part, passée à travers la
franchise déclarée, redonne les frais : exacte sous le plafond, un minimum (« ≥ »)
au-delà, puisque tout coût plus grand laisse la même part.

**La franchise se déclare** (`data/health.json`) : le calcul en dépend deux fois, pour
retrouver les frais et pour remonter les primes. Tant qu'elle ne l'est pas, la page
suppose 300 et le demande. Les frais affichés partent de la dernière année entière ; une
année se choisit d'un clic, un montant se tape (`?costs=`). La courbe donne le coût
annuel de chaque franchise selon les frais, et le seuil sous lequel la plus haute coûte
moins que la plus basse.

## En chemin

La règle « Assura » attrapait « La Mobilière Assurances » : l'assurance ménage était
classée en assurance maladie. Le motif est devenu `Assura(?!nce)`.
