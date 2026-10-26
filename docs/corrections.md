# Reclassement en masse et fusion de bénéficiaires

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

Le cas utile n'est pas « les 60 lignes affichées » mais « les centaines du filtre courant ».
`views.common._filtered()` est donc partagé entre la table et l'endpoint bulk : « tout ce qui
correspond » désigne exactement ce que l'écran montrait, sans dérive possible.

Les cibles du bulk sont préfixées `to_*` (`to_category`, `to_bucket`). Elles partageaient
d'abord les noms du filtre (`category`, `bucket`), ce qui faisait de « tout ce qui est
dans le bucket X » et « déplacer vers le bucket Y » le même paramètre — la sélection
revenait vide.

Un bulk fait un seul `save()` : des centaines de corrections écrites une à une réécriraient
le fichier autant de fois, et un plantage à mi-parcours laisserait une correction à moitié appliquée que
rien n'enregistre comme incomplète.

**Les Twint sans bénéficiaire se trient à la main, une touche chacun** (`/corrections/tri`,
`pages/Triage.tsx`, nourri par `/api/triage`).
Sur le relevé réel, des centaines de paiements Twint n'impriment que « Paiement Twint » : ni
bénéficiaire, ni message, ni lieu. Ils étaient rangés en « Transferts P2P », ce qui
affirmait ce que personne ne sait — Twint paie aussi les parcmètres et les machines à
café, et beaucoup valent ~2 CHF. Ils sont désormais « Twint non identifié »
(`categories.TWINT_UNKNOWN`, bucket non classé) ; « Transferts P2P » ne garde que les
virements à une personne nommée.

Aucune règle ne peut les classer, et aucun modèle de langage non plus : l'information
n'est pas sur la ligne. La page rend donc le tri manuel peu coûteux plutôt que de le
deviner :

- un Twint à la fois, le plus récent d'abord (celui dont on se souvient) ; une catégorie
  = une touche 1–9 ou un toucher, `S` passe, `Z` annule le dernier. Sur le téléphone, la
  carte se glisse de côté pour passer ;
- pour rafraîchir la mémoire : le jour de la semaine, les autres mouvements du jour
  (souvent une carte avec un lieu), et **ce que le titulaire a déjà décidé au même
  montant** — la seule piste honnête, puisque le montant est tout ce que la ligne porte.
  Elle est *montrée* (bouton souligné), jamais appliquée d'office ;
- les montants récurrents (au moins `TRIAGE_GROUP_MIN` = 3) se classent d'un coup, en
  épingles (`/api/triage`, action `group`) ;
- les catégories viennent dans l'ordre de ce qui a déjà servi pour des Twint, pour que
  les touches tombent sur les habituelles ;
- **une suggestion apprise de ces décisions** (`twint.py`) : la tranche de montant, le
  jour, ce qui a été payé par carte ce jour-là, un séjour à l'étranger proche, un
  montant qui revient chaque mois. Elle est mesurée tranche par tranche sur les Twint
  déjà classés, chacun prédit sans lui-même, et n'apparaît que dans une tranche où elle
  a été juste ; la carte affiche ce taux. Montrée, jamais appliquée ;
- un Twint de 100 CHF ou plus autour d'un séjour à l'étranger rappelle le séjour, et
  la convention du titulaire : une part de voyage remboursée se classe en « Loisirs &
  voyages », pas en « Transferts P2P » ;
- une tranche presque toute d'une catégorie se classe d'un coup, en épingles, et
  s'annule depuis le toast (action `band`, puis `restore`) : `docs/assistant.md`.

Chaque choix est une épingle, pas une règle : il n'y a pas de bénéficiaire sur lequel
écrire une règle. **Et l'épingle garde le bucket déjà décidé** : beaucoup des Twint réels
portaient une épingle Want/Need sans catégorie, posée dans la table. `pin()` remplace
l'entrée entière, donc y écrire une catégorie aurait re-dérivé le bucket de la catégorie
(Transport → Need) et défait la décision — des dizaines d'un coup avec « Classer les N ». Le tri
écrit donc la catégorie *par-dessus* le bucket existant (`_pin_category`), son annulation
rend l'épingle bucket seul, et les groupes par montant passent par le tri, pas par
`/api/reclassify/bulk`. Le tri refuse (409) toute ligne qui n'est pas un Twint non
identifié.

**Une règle posée depuis une ligne fait bouger cette ligne** (15.10). Une épingle
l'emporte sur la règle de son bénéficiaire — c'est ce qui laisse un paiement isolé
différer. Mais une transaction épinglée « Non catégorisé », puis glissée sur
Restaurants (une règle, par défaut), restait où elle était, alors que le message
annonçait le changement. La ligne sur laquelle on agit retire donc de sa propre épingle
ce que la règle contredit (`Overrides.yield_to_rule`) — la catégorie si la règle en
nomme une, le bucket si elle en nomme un ; un bucket épinglé survit à une règle de
catégorie, même leçon que les Twint. Les autres lignes du bénéficiaire gardent leurs
épingles : ce sont des exceptions décidées. Même chose pour les lignes d'un
reclassement en masse « en règles ».

**Annuler rétablit ce qui était là, pas « rien ».** Une règle reformulée par-dessus
l'ancienne du même bénéficiaire, ou une épingle écrite sur une épingle bucket seul,
s'annulaient en ne laissant ni règle ni épingle. Chaque correction note avant d'agir
l'état exact des épingles et règles qu'elle touche (`snapshot`, avec la place de la
règle : quand deux règles attrapent une ligne, la dernière gagne), et l'annulation le
remet (`restore`).

**Les alias fusionnent plusieurs orthographes d'un même bénéficiaire.** Les banques ne sont
pas cohérentes — la même régie est imprimée « Muster Verwaltung AG » et
« Muster Verwaltungs AG », et tous les totaux la comptent alors comme deux personnes.
Deux formes : un alias exact, et un alias par motif pour toute une enseigne (des dizaines
d'orthographes de Coop sur un relevé, une par caisse — les lister une à une serait une liste qui grandit
chaque mois). L'exact l'emporte sur le motif, étant la déclaration la plus spécifique.

Les alias s'appliquent *avant* les règles, pour qu'une règle écrite sur le nom conservé
attrape aussi les autres. Ils ne s'enchaînent jamais : poser A→B puis B→C repointe A sur C.

**La fusion ne déplace pas de catégorie.** `classify_all` tourne avant `overrides.apply`,
donc une station-service Coop reste en transport même si elle s'affiche « Coop ».
`top_merchants` reporte alors la catégorie qui porte l'argent, pas celle de la première
ligne — et ne signale un mélange que sous 95 %, sinon « 2 catégories, 100 % » énonce
quelque chose de faux.

## La page Corrections (19.10)

- **Le classement** en tête (`tidy.coverage`) : la part des francs dépensés et des
  paiements qui ont une catégorie, et ce qui reste — les Twint sans bénéficiaire (vers
  le tri) et les paiements « Non catégorisé » (vers la table filtrée `?todo=1`).
- **Fusions proposées** (`tidy.merge_suggestions`) : des bénéficiaires qui commencent
  par les mêmes mots et dépensent à 80 % dans une même catégorie — une enseigne
  imprimée par caisse. Le nom proposé est le début commun (« Régie du Centre » pour
  « … SA » et « … S.A. »), refusé s'il ne nomme qu'un genre de lieu (« Restaurant Le »
  ce sont deux restaurants : `GENERIC`). Montrées avec chaque orthographe, appliquées
  sur un clic, annulables.
- **Une règle ou une épingle se modifie en place** (action `edit`) : sa portée reste,
  là où retirer puis refaire la perdait entre les deux. **Retirer, modifier, fusionner
  s'annulent depuis le toast** : la réponse porte le corps qui rétablit (`restore`
  d'un `snapshot`, `realias`, ou le retrait de la fusion).
- Les corrections se trient : récentes, impact (francs touchés), A → Z.

Côté table : `?amin=&amax=` (taille du montant, en francs), `?fix=1` (corrigées),
`?todo=1` (à classer) passent par `_filtered` — la table, l'export et le bulk voient
les mêmes lignes. Au-dessus, « Ce filtre en bref » (`api/transactions.summary`) :
sorties, entrées, solde, paiement médian, sorties dans le temps, où, et les
bénéficiaires principaux ; une catégorie ou un nom cliqué filtre.

## Impôts et Administration, deux catégories (20.10)

« Impôts & administration » mêlait l'impôt et tout ce qu'on paie à l'État ou à un
service public. Le titulaire les veut séparés :

- **Impôts** : l'administration fiscale (`Impôts`), la taxe militaire (`Taxe militaire`) ;
  un remboursement reste `Remboursement`.
- **Administration** : `Poursuites` (office des poursuites ou des faillites), `Poste`,
  `Documents & autorités` (contrôle des habitants, OCPM, office des véhicules, plaques,
  état civil, registre du commerce, passeport…), `Amendes` (service des contraventions).

Les règles des poursuites sont testées avant celles de l'impôt : « Office des poursuites »
était classé en impôts. **Rien d'écrit avant n'est perdu** : une épingle, une règle de
bénéficiaire ou une règle personnelle qui nomme encore « Impôts & administration » est lue
sous le nouveau nom (`categories.current`) : `Impôts` et `Remboursement` vont aux Impôts,
`Services publics` devient `Administration · Documents & autorités`, le reste va à
l'Administration. Les fichiers eux-mêmes ne sont pas réécrits.

## Filtrer par compte (26.10)

`?acct=` dans `/transactions` : les lignes d'un seul compte — `principal` (le compte qui
nomme le ledger, `Transaction.account` vide), `revolut`, ou le nom d'un compte secondaire.
Le choix n'apparaît que si la période mêle plusieurs comptes ; chacun est nommé par sa
banque (`views.common.account_options` : le principal par la banque de son dernier import —
le champ `bank` du journal, UBS, sinon l'extension du fichier, comme le rappel de relevé en
retard). Le filtre passe par `_filtered`, donc la table, le reclassement « tout le filtre » et
l'export CSV/xlsx voient les mêmes lignes. La recherche trouvait déjà « revolut » : le nom du
compte est dans ce qu'elle lit.
