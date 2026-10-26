# Revue du mois

<!-- Lu à la demande, quand on travaille sur `review.py` ou le panneau
     « Revue du mois » (voir « Où lire avant de toucher » dans CLAUDE.md). -->

Le tableau de bord répond bien quand on le questionne, mais il ne dit jamais ce qui a
*changé*. `review.month_review` compare un mois à tout ce que le ledger tient avant lui
et garde quatre listes courtes ; `Review` (`frontend/src/pages/dashboard/Panels.tsx`) les
affiche juste sous les indicateurs.

**Seulement sur une fenêtre d'un mois calendaire**, le mois en cours compris (du 1er au
dernier jour du ledger) : ailleurs, « ce mois-ci » n'a pas de sens. Sur le mois en
cours, la revue le dit (« mois en cours, au 21.09 ») : un nouveau bénéficiaire ou un
débit doublé est aussi réel le 21 que le 31, et une catégorie déjà au-dessus de son
habitude n'y redescendra pas. Moins de trois mois entiers avant le mois : pas de revue,
« inhabituel » a besoin d'un habituel.

**Tous les seuils sont nommés en tête de `review.py`, et chacun dit pourquoi il ne se
déclenche pas sur le cas ordinaire.** Une revue qui crie au loup apprend à la sauter —
la leçon du panneau « Engagements sans passage récent ». Calibrée sur le ledger réel :
une médiane de deux signalements par mois.

- **Un prix qui a changé** ne se lit que sur un prix *fixe* : les trois derniers débits
  d'accord à 1 % près, facturés au plus environ une fois par mois (écart médian ≥ 20
  jours). Sans la seconde condition, la cantine à 8.00 et son plat à 11.50 passeraient
  pour une hausse de prix ; sans la première, chaque facture d'énergie. La comparaison
  se fait **dans la devise du débit** : un abonnement de 20 USD coûte chaque mois un
  autre montant en francs, et c'est le taux de change, pas le fournisseur. Trouvé sur le
  ledger réel : la hausse d'un franc d'un abonnement mobile.
- **Un nouveau bénéficiaire** : jamais payé avant ce mois. Un virement nouveau compte
  dès 50 CHF (une nouvelle régie, un nouvel office des impôts) ; un nouveau commerçant
  par carte seulement dès 250 CHF. Mesuré sur le ledger réel, la plupart des mois
  apportaient quatre ou cinq nouveaux restaurants, et leur liste enterrait le seul
  nouveau bailleur.
- **Un débit peut-être doublé** : même bénéficiaire, même montant dans la même devise, à
  moins de trois jours, dès 20 CHF (deux cafés à 4.50 sont deux cafés). Pas chez un
  bénéficiaire payé plus de quatre fois dans le mois : deux montants égaux y sont
  l'habitude.
- **Une catégorie au-dessus de son habitude** : au-delà de Q3 + 1,5 × IQR de ses mois
  entiers (les mois sans dépense comptent pour zéro), et d'au moins 100 CHF de plus que
  sa médiane — les quartiles et la médiane, comme partout, qu'une facture annuelle
  n'étire pas. Une catégorie que l'historique sait saisonnière pour ce mois
  (`plans.seasonal_one_offs`, deux ans de données) est comparée au même mois de l'an
  passé (× 1,5), sinon la prime de décembre serait signalée chaque année.

**Une liste vide le dit en toutes lettres.** « Rien d'inhabituel » est une réponse ; un
blanc se lirait comme un panneau en panne.

**Chaque garde-fou a un test qui échoue quand on l'enlève** (`tests/test_review.py`),
vérifié en le désactivant : le relevé fictif ne contenait pas les cas qui les font
mordre (la cantine qui finit un mois sur son plat à 11.50, un dollar qui saute de 3 %
après cinq mois stables), qui sont donc construits à la main.
