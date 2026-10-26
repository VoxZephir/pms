# Faire entrer un relevé : Téléchargements, import, rappel

<!-- 15.10.2026 : l'utilisateur trouvait l'inbox trop manuelle. La surveillance
     automatique, écartée le 02.08, est revenue avec ce changement d'usage :
     l'app tourne désormais en permanence (accès téléphone, docs/acces-distant.md). -->

## Ce qui reste manuel, et pourquoi

**Aller chercher le relevé chez la banque.** Swissquote n'exporte qu'un PDF (vérifié :
ni camt.053, ni CSV, ROADMAP point 1) et n'offre aucune API aux particuliers ; l'open
banking suisse (bLink, SIX) est réservé aux prestataires sous contrat. Un robot qui se
connecterait à la place de l'utilisateur devrait stocker le mot de passe bancaire et
contourner la double authentification : exclu. Revolut, banque européenne, est joignable
par un agrégateur DSP2 — mais ce tiers lirait toutes les transactions, et le
consentement est à renouveler tous les 90 à 180 jours : un geste manuel remplacé par un
autre, les données en plus hors de chez soi. Pas retenu.

Tout ce qui suit le téléchargement est automatique.

## Les trois portes, un seul chemin (`intake.take`)

- **Téléchargements du PC** (`web/watcher.py`) : le geste ordinaire. Télécharger le
  relevé, c'est tout.
- **`/importer`** : depuis le téléphone, ou un fichier rangé ailleurs.
- **`inbox/` + ⟳ ou `run.bat`** : la voie d'origine, toujours là.

Les deux premières passent par `intake.take` : le fichier est rangé là où sa banque est
lue (`banks.placement`), ingéré tout de suite, et retiré d'`inbox/` si son parser n'en
tire rien — laissé là, il ferait échouer chaque lancement suivant. `intake.LOCK`
sérialise toutes les ingestions du serveur (⟳, import, surveillance) : deux à la fois
enregistreraient chacune le ledger qu'elles ont lu, et la seconde perdrait les lignes de
la première.

## La surveillance des Téléchargements

Le processus qui sert l'app (pas le superviseur du reloader, qui ne sert jamais) regarde
le dossier Téléchargements de Windows — le vrai, lu par `SHGetKnownFolderPath`, où que
l'utilisateur l'ait déplacé — toutes les 60 s, et une fois au démarrage.

- **Reconnu au contenu, jamais au nom** (`banks.recognise`). Chaque banque déclare son
  test dans `banks.BANKS` : pour Swissquote, la page de couverture porte « Swissquote »,
  « Relevé de transactions » et une période `JJ.MM.AAAA à JJ.MM.AAAA` (vérifié sur les
  six vrais relevés, 50–90 ms par fichier, une seule page lue) ; pour Revolut, la ligne
  d'en-tête porte toutes les colonnes du compte. Un relevé renommé reste reconnu ; une
  facture, un billet, le relevé crypto Revolut (autres colonnes) ne le sont pas, et ne
  sont jamais touchés.
- **Un fichier est jugé une fois par version** (nom, taille, date) : ce qui n'est pas un
  relevé n'est pas relu chaque minute, et un relevé refusé n'est pas réessayé avant
  d'avoir changé.
- **5 s de repos** avant d'être lu : un navigateur renomme un téléchargement fini, mais
  un autre outil peut écrire sur place.
- **Déplacé, pas copié** : une fois ingéré, il quitte Téléchargements pour `inbox/`, qui
  est sauvegardé. Le même relevé téléchargé deux fois ne laisse ni doublon dans `inbox/`
  ni copie dans Téléchargements.
- **Refusé, il reste où il est** (autre IBAN, aucun mouvement lu…) ; la raison s'affiche
  sur `/importer` et dans la console.
- Le fil ne meurt pas d'un passage raté : l'erreur est notée, le suivant réessaie.
- `python -m pms.web --no-watch` l'éteint, `--watch DOSSIER` en surveille un autre.

Mesuré au premier lancement (15.10) : 81 fichiers dans Téléchargements, 48 PDF/CSV
examinés en 2,9 s, aucun relevé — rien n'a été pris.

## Le rappel

Le tableau de bord signale chaque banque dont le dernier relevé **s'arrête** depuis plus
de 14 jours (`news.LATE_DAYS`, la moitié d'un mois que personne n'a regardé), avec le
lien où le chercher. Lu dans le journal des imports, par le compte que chaque import a
alimenté, et sur la période couverte — pas sur le dernier mouvement : une semaine calme
n'est pas un relevé en retard. Une banque jamais importée n'est pas en retard. Pas de
bouton pour le masquer : il part de lui-même quand le relevé arrive.

Le lien Swissquote mène à la page d'accueil publique, pas à une URL de connexion : la
banque met en garde contre les fausses pages de login, et le bouton de connexion est en
haut de son accueil.

## Le relevé ISO 20022 (camt.053) : la plupart des banques suisses

Le camt.053 est le format de relevé commun aux banques suisses depuis le passage à ISO
20022 : PostFinance, UBS, Raiffeisen, les banques cantonales le proposent dans l'e-banking à
côté du PDF (souvent « Kontoauszug ISO 20022 », « camt.053 », ou un export XML). Un seul
parser (`camt.py`) les lit tous, déposé dans `inbox/camt/` ou téléchargé.

Écrit d'après la norme et contrôlé contre son schéma (`camt.053.001.08`), **pas encore
contre l'export réel d'un client** : le premier vrai fichier est la vérification qui reste.
`reconcile()` vide sur ce fichier est, comme ailleurs, le critère d'acceptation.

- **Pas de solde par ligne dans le format.** Chaque relevé (`Stmt`) donne un solde
  d'ouverture et un de clôture. Le solde d'une ligne est donc calculé depuis l'ouverture,
  et la dernière ligne de chaque relevé porte la clôture imprimée par la banque :
  `reconcile()` prouve que chaque relevé tombe juste et que les relevés s'enchaînent,
  mais une ligne perdue se signale sur la dernière ligne de son relevé, pas sur elle.
  Une banque qui livre un relevé par jour localise donc au jour.
- **La référence** est celle de la banque (`AcctSvcrRef`) ; sans elle, une référence
  dérivée du contenu de la ligne et de son rang parmi les lignes identiques du jour.
- **Une écriture groupée** (plusieurs `TxDtls`) devient une ligne par bénéficiaire quand
  leurs montants font celui de l'écriture.
- **Seules les écritures comptabilisées** (`BOOK`) entrent ; une réservation peut encore
  changer.
- **Le vocabulaire** suit le code de transaction bancaire (domaine / famille / sous-famille) :
  carte, virement reçu ou émis, recouvrement, intérêts, frais ; « TWINT » dans le texte
  d'un débit en fait un « Paiement Twint ». Un virement entre deux comptes du même fichier
  est interne ; entre deux devises, c'est un change dont chaque jambe porte le montant de
  l'autre, comme chez Swissquote.
- **Pas de pays** : le format n'a pas d'adresse structurée pour un paiement par carte, la
  vue géographique reste vide pour ces lignes.
- **Le premier compte en francs du fichier est le compte principal** : son IBAN nomme le
  ledger. Les autres comptes sont secondaires, nommés `compte-1234` d'après la fin de
  leur IBAN.

## Le relevé de quelqu'un d'autre, par mégarde

Un ledger suit un titulaire : le compte principal a un IBAN, et un relevé qui en imprime
un autre est **refusé entier** (`ledger.ForeignAccount`), rien n'en est fusionné. Par
l'import ou les Téléchargements, le fichier est retiré d'`inbox/` et la raison affichée ;
déposé à la main dans `inbox/`, chaque lancement le signale et continue avec les autres
(`ingest(strict=False)`). Un autre titulaire a sa propre copie de l'app.

Un export qui n'imprime pas d'IBAN (le CSV Revolut) ne peut pas être reconnu comme
étranger : il entrerait. Pour défaire : `--status` donne l'empreinte de l'import,
`--forget <sha256>` en retire les lignes et l'entrée du journal — puis supprimer le
fichier d'`inbox/`, sinon le lancement suivant le réimporte. En dernier recours,
`--restore` remet la sauvegarde d'avant.

## UBS (26.10)

`ubs.py`, `inbox/ubs/` : l'export PDF « Account transactions » de l'e-banking UBS, en
anglais. Lu sur un vrai export (plein, caviardé) : `reconcile()`
vide, ouverture + mouvements = clôture au centime. Le relevé n'est pas recopié dans le
dépôt ; les tests tournent sur un export inventé à la même géométrie
(`tests/synthetic_ubs.py`).

- **Une ligne par mouvement, du plus récent au plus ancien** : date de transaction sur
  date de comptabilisation, une description d'une ou deux lignes, parfois une ligne grise
  plus petite qui dit ce qu'est le mouvement, débit (aligné à droite vers x 335) ou crédit
  (vers x 397), date de valeur, solde après le mouvement. La chaîne des soldes tient dans
  cet ordre, par date de transaction : renversée, elle est chronologique. La date d'un
  mouvement est sa date de transaction.
- **Les mots n'ont pas d'espace** : l'écart entre deux mots fait ~2,5 pt, pdfplumber les
  coupe à 1 pt (son défaut de 3 les colle). Un débit de quatre chiffres commence avant
  x 300 : la description est bornée par ses deux bords.
- **Un export s'arrête à 500 mouvements.** Il imprime alors « (500 transactions du … au …) » :
  la période couverte est celle-là, pas celle demandée — les mois d'avant manquent, ils ne
  sont pas calmes. Pour tout l'historique, exporter par tranches de moins de 500 mouvements ;
  les tranches qui se chevauchent se dédoublonnent.
- **Aucune référence imprimée** : elle est dérivée du contenu (dates, montant, description,
  ligne grise), avec un rang parmi les lignes identiques du jour.
- **Le vocabulaire** est ramené à celui de l'analyse : « Debit card payment » et un Twint
  payé à un commerce (« X; Payment UBS TWINT ») sont des paiements par carte (le commerce est
  nommé, les règles le lisent) ; un Twint avec une personne (« Debit UBS TWINT », « Credit UBS
  TWINT ») est « Paiement Twint », la personne en contrepartie ; « e-banking payment order »
  « Versement pour X » ; un salaire « Paiement entrant - salaire » (classé Revenus · Salaire avant toute règle fiscale : un canton employeur reste un salaire), un crédit « Paiement entrant » ; « direct debit »
  « Recouvrement direct » ; « PayNet Order » « Facture eBill » ; le Bancomat « Retrait » /
  « Dépôt d'espèces » ; « Balance closing of service prices » des frais (souvent 0.00) ;
  « Interest calculation balance » des intérêts. **La facture de la carte de crédit UBS**
  (ligne grise « VIS1W… ; direct debit ») est « Facture carte de crédit » : ce qu'elle a
  payé est sur le relevé de la carte, pas ici.
- **Rangement** : `banks.recognise` reconnaît l'export à son contenu (« UBS Switzerland AG »
  et les colonnes) et l'import le range dans `inbox/ubs/`. Déposé à la main à la racine
  d'`inbox/`, il est quand même lu par le parser UBS (`banks._pdf`). Le compte est le
  compte principal : c'est l'export de quelqu'un dont UBS est la banque.
- **Pas encore lu** : l'export en français ou en allemand (les libellés changent), le pays
  d'un paiement par carte (UBS ne l'imprime pas : les séjours à l'étranger des Projets ne se
  détectent pas sur ce relevé).

## Une journée coupée par un relevé téléchargé pendant ce jour (26.10)

Un relevé téléchargé un jour J ne contient que les mouvements de J déjà passés,
numérotés dans ce qu'il contient (`Transaction.seq`, le rang dans la journée). Le suivant
contient toute la journée, numérotée autrement. Gardées chacune avec le rang de son relevé,
les lignes de J se mélangeaient et le solde cassait au milieu de la journée — « des
mouvements manquent entre le JJ.MM et le JJ.MM », le même jour deux fois. `Ledger._reorder` : quand le relevé qui
arrive contient toutes les lignes que le ledger a pour un (jour, compte, devise), son ordre
fait foi pour toutes ; quand il en contient moins (un ancien relevé partiel réimporté), l'ordre
du ledger reste. Un ledger déjà touché se répare en relisant les relevés, le plus récent en
dernier : `run.bat --reparse`. Le tableau de bord le dit quand la rupture tient dans un seul
jour.

## Un mouvement importé deux fois sous deux formats (26.10)

L'export Revolut en `fr-ch` écrit un frais « 0 » et un montant « 35.1 », celui en `fr-fr`
« 0.00 » et « 35.10 ». La référence d'une ligne Revolut est dérivée de ce texte : la même
ligne, venue des deux exports, avait deux références, entrait deux fois, et le solde cassait
de son propre montant. Le calcul de la référence n'a pas été changé —
toutes les lignes déjà importées en changeraient, et leur réimport les doublerait.
`ledger.content_of` reconnaît une ligne à ce qu'elle est : compte, devise, jour, montant et
solde après elle. À la fusion, une ligne inconnue par sa référence mais connue par son contenu
est la même (comparée seulement à ce que le ledger tenait avant cet export : deux lignes égales
d'un même export restent deux). `Ledger.dedupe`, à chaque ingestion, retire un tel doublon
déjà enregistré quand ses deux copies viennent de deux imports différents ; la console le dit.
