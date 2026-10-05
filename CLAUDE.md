# PMS — analyse de relevés bancaires

Pipeline Python qui lit un relevé de transactions bancaire, le classe, et le rend
explorable dans une app Flask à navigation temporelle. Le parser livré est celui du
relevé PDF Swissquote ; une autre banque se branche par un parser qui produit le même
`Statement` (section « Ajouter une banque »).

Il a existé un rapport HTML statique à côté. C'était un brouillon, il est supprimé, et il
ne doit pas revenir : sa géométrie de graphiques vit maintenant dans `web/charts.py`, son
unique consommateur. Ne pas reproposer de le réintroduire — pour sortir des données, il y
a l'export CSV/xlsx.

## Lancer

```bash
run.bat                                  # ingestion + app Flask (défaut)
run.bat --test                           # la suite de tests
.venv/Scripts/python -m pms              # ingestion + rapprochement des soldes
.venv/Scripts/python -m pms --check      # idem, sortie non nulle si un solde casse
.venv/Scripts/python -m pms --reparse    # relire aussi les PDF déjà importés
.venv/Scripts/python -m pms --status     # état du ledger et historique des imports
.venv/Scripts/python -m pms --forget <sha256>   # oublier un import erroné (sha vu dans --status)
.venv/Scripts/python -m pms --finpension        # régénérer le snapshot 3a depuis inbox/finpension/
.venv/Scripts/python -m pms --capture c.json    # fusionner une capture d'épargne (skill /epargne)
.venv/Scripts/python -m pms --3a-value X --on AAAA-MM-JJ   # une valeur 3a lue dans l'app
.venv/Scripts/python -m pms --ibkr-journal      # l'export de transactions IBKR d'inbox/ibkr/
.venv/Scripts/python -m pms --export out.xlsx   # ou out.csv
.venv/Scripts/python -m pms --from 2025-01-01 --to 2025-12-31
.venv/Scripts/python -m pms.web          # app Flask
.venv/Scripts/python -m pytest tests -q  # ~50 s, ruff et navigateur compris
.venv/Scripts/python -m ruff check src tests
```

Le paquet est installé en éditable (`pip install -e .`), donc pas de `PYTHONPATH`
à positionner. Si un import échoue, relancer `.venv/Scripts/pip install -e .`.

**Un PDF déjà importé n'est pas relu.** L'empreinte est comparée au journal des
imports *avant* le parsing — c'est le parsing qui coûte (14 s pour un relevé de deux
ans), et chaque lancement le repayait pour chaque PDF resté dans `inbox/` : 17 s pour
trois relevés déjà connus, 0,6 s depuis. `--reparse` force la relecture, pour
confronter les lignes stockées à un parser modifié (un écart est signalé en
conflit, jamais écrasé).

## Architecture

```
                                                    ┌─▶ export ──▶ *.csv / *.xlsx
inbox/*.pdf ─▶ parser ─▶ ledger.json ─▶ categories ─┤
                  │          │             analysis ┴─▶ web ──▶ http://127.0.0.1:5000
             reconcile()  gaps()           buckets
```

| Module | Rôle |
|---|---|
| `models.py` | `Transaction`, `AccountSummary`, `Statement` |
| `parser.py` | PDF → transactions, par géométrie ; `reconcile()` valide |
| `ledger.py` | accumulation multi-imports, déduplication, détection de trous |
| `categories.py` | règles marchand → catégorie/sous-catégorie |
| `analysis.py` | agrégations, conversion CHF, coûts custodian, récurrence, géographie, **découpage par période et séries à granularité variable** |
| `buckets.py` | Need / Want / Save, et leurs parts mois par mois |
| `review.py` | revue du mois : ce qui a changé par rapport à l'historique |
| `export.py` | CSV et xlsx de la vue courante ; écrivain OOXML sans dépendance |
| `plans.py` | suggestions de ponctuels saisonniers, `data/plans.json`, projection de trésorerie sur 12 mois |
| `budgets.py` | objectifs mensuels par catégorie, `data/budgets.json`, jauges dans le panneau mensuel |
| `finpension.py` | journal CSV + rapports de performance du 3a, `data/finpension.json` |
| `ibkr.py` | lit `data/ibkr.json` — l'épargne hors relevé (Interactive Brokers), snapshot figé |
| `ibkr_history.py` | l'export « Transaction History » d'IBKR : versements, frais, positions depuis 2023, valeur reconstruite chaque semaine (`--ibkr-journal`) |
| `snapshots.py` | fusionne une capture d'épargne sans réécrire l'historique (`--capture`), dit où s'arrête chaque série (`--status`) |
| `web/store.py` | charge le ledger une fois, sert des vues par période |
| `web/periods.py` | résolution de fenêtre, préréglages, fil d'ariane |
| `web/charts.py` | géométrie de tous les graphiques — l'unique implémentation |
| `web/news.py` | le relevé qui vient d'arriver : annonce et mois d'arrivée |
| `web/views/` | routes, un module par page : `common` (blueprint, store, modes d'URL,
filtre et tri de la table), `dashboard`, `transactions`, `corrections`, `previsions`,
`analyse`, `savings` (arithmétique du panneau Épargne, sans route), `system` (santé,
réingestion, redémarrage) |

## Où lire avant de toucher

Le raisonnement détaillé de chaque fonctionnalité vit dans `docs/`, pas ici : ce
fichier est chargé à chaque session, eux seulement quand on y travaille. Lire le bon
**avant** de modifier — chaque décision y est justifiée, et la plupart ont été prises
contre une première version qui semblait évidente.

| Avant de toucher | Lire |
|---|---|
| `plans.py`, `/previsions`, `views/previsions.py`, la courbe de patrimoine | `docs/previsions.md` |
| `/analyse`, le panneau « Dépenses par mois » et ses budgets, `plans.monthly_profile` | `docs/analyse.md` |
| le bouton ⟳, le sommaire, le brush, le préchargement, les panneaux repliés, les panneaux « Engagements sans passage récent », « D'où vient l'argent » et « Évolution des parts » | `docs/app-web.md` |
| le panneau Épargne, `ibkr.py`, `finpension.py`, `snapshots.py`, `views/savings.py`, la skill `/epargne` | `docs/epargne.md` |
| `export.py`, les routes d'export, l'écrivain xlsx | `docs/export.md` |
| le reclassement en masse, les alias de bénéficiaires, le tri des Twint (`/reclasser/tri`) | `docs/corrections.md` |
| `review.py`, le panneau « Revue du mois » | `docs/review.md` |

## Ajouter une banque

Le README invite les utilisateurs d'une autre banque à te demander d'adapter le code à
leur relevé. Quand on te le demande : lire le relevé déposé dans `inbox/` (son format,
ses colonnes, son vocabulaire), écrire le parser, le brancher, puis prouver qu'il est
juste avec `reconcile()` sur ce vrai relevé — pas seulement des tests verts. Ne jamais
recopier une ligne, un nom ou un IBAN de ce relevé dans le code, les tests ou la doc :
les formes manquantes vont dans `tests/synthetic.py`, inventées.

Le contrat complet, champ par champ, est dans `README.md` (« Brancher une autre
banque ») — c'est aussi la doc des contributeurs. L'essentiel pour ne pas le casser :

- **Un parser = une fonction `parse(path) -> Statement`**, passée à `ledger.ingest`.
  Rien en aval du parser ne doit apprendre le format d'une banque ; ce qui varie se
  normalise dans le parser.
- **`(référence, devise)` doit être stable entre deux exports** qui se chevauchent,
  sinon le ledger double les lignes. Une banque sans référence imprimée : la dériver
  du contenu de la ligne et de son rang dans la journée, jamais d'un compteur global.
- **`reconcile()` vide sur un vrai relevé est le critère d'acceptation**, comme pour
  Swissquote. Un parser qui ne remplit pas `balance` perd la localisation des ruptures ;
  le dire, ne pas fabriquer de soldes.
- Le vocabulaire Swissquote encore codé en dur (`FX_KINDS`, `PEER_KINDS`,
  `INCOMING_KINDS`, `CARD_KIND`, `"Versement pour "`, le pays en fin de `location`) :
  le parser d'une autre banque normalise `kind` vers ces libellés plutôt que
  d'ajouter des branches par banque dans l'analyse.
- Le CHF reste la devise de référence partout ; une banque en EUR est un chantier à
  part, pas un paramètre.
- `cli.py` et `web/views/system.py` appellent `parse_statement` sur `inbox/*.pdf` :
  ce sont les deux seuls points de branchement. Pas de détection automatique — en
  ajouter une le jour où deux banques coexistent, pas avant.

## Faits établis sur le relevé Swissquote (à ne pas re-découvrir)

**Le PDF.** 104 pages, trois sections devises (CHF p2-91, EUR p92-102, USD p103-104),
2166 transactions du 30.07.2024 au 30.07.2026.

**`pdftotext -layout` ne marche pas ici.** La cellule Information s'étale sur 2-3 lignes
alors que les montants tiennent sur une, donc le mode texte dérive et apparie un montant
avec la mauvaise date. Le parsing se fait sur les coordonnées des mots. Colonnes (595pt de
large, constantes sur toutes les pages) :

| x0 | colonne |
|---|---|
| < 75 | Date |
| < 145 | Référence |
| < 300 | Information (déborde sur les lignes suivantes) |
| ≥ 300, x1 ≤ 400 | Frais et taxes |
| ≥ 300, x1 ≤ 446 | Montant (aligné à droite sur x1 = 444) |
| 446–520 | Date de valeur |
| ≥ 520 | Solde (aligné à droite sur x1 = 569) |

**La colonne « Frais et taxes » est vide sur les 104 pages.** Swissquote ne facture aucune
commission explicite sur ce compte. Ne pas chercher les frais là.

**Le coût réel du custodian est la marge de change.** Chaque conversion imprime un taux de
référence *et* le montant CHF réellement débité, et les deux ne concordent pas : l'écart
vaut 0.97 % (médiane), très stable sur les 63 opérations — soit 62.00 CHF au total. C'est
une marge tarifaire, pas un aléa de marché.

**La clé d'identité d'un mouvement est `(référence, devise)`, pas la référence seule.** Une
conversion imprime la *même* référence sur ses deux jambes (débit CHF et crédit EUR/USD).
2103 références distinctes pour 2166 lignes = 63 conversions.

**La banque n'ordonne pas les lignes d'un même jour par référence** (le 17.08.2024 imprime
635995325 avant 635995310). D'où le champ `Transaction.seq` : la position de la ligne au
sein de sa propre date. Trier par `(date, référence)` fabrique des ruptures de solde
fantômes sur chaque journée concernée.

**Les transferts de change sont des mouvements internes, pas des dépenses.** Compter à la
fois la jambe CHF et l'achat en devise double-compterait. Les comptes EUR et USD ouvrent et
ferment à 0.00 exactement, ce qui rend le calcul exact : la somme des jambes CHF *est* le
coût en francs de toutes les dépenses en devises.

**Le bucket `Save` a deux lignes : quelques milliers de CHF vers Interactive Brokers le
24.09.2026, et quelques milliers qui en sont revenus le 20.12.2024** (un retrait : la ligne nomme le titulaire,
seul le BIC `IBKRUS33` dit IBKR). Le compte IBKR existe depuis le 13.09.2023 — son
historique complet vient de l'export CSV, pas du connecteur (un an seulement), et
`docs/epargne.md` le détaille ; le 3a a reçu son versement unique en mai 2024. L'épargne affichée est donc presque
entièrement du solde non dépensé : `buckets.summarise()` sépare `Versé` de `Non dépensé`.
Ce virement est aussi un **versement IBKR** : il n'est pas de la performance
(`ibkr.flows`, `docs/epargne.md`) — ne jamais recalculer un rendement IBKR comme le
rapport de deux NAV. La part non dépensée est dessinée
**creuse** dans la barre et n'est pas cliquable — elle n'a aucune transaction derrière elle,
un lien tomberait sur une table vide.

**Un Twint envoyé n'imprime que « Paiement Twint ».** Ni bénéficiaire, ni message, ni
lieu : 313 lignes dont seul le montant et la date sont connus. Elles sont « Twint non
identifié », pas « Transferts P2P » (Twint paie aussi des parcmètres), et ne se classent
qu'à la main — `/reclasser/tri`. Ne pas proposer de les deviner, par règle ou par modèle :
l'information n'est pas sur la ligne, et l'app TWINT n'offre pas d'export.

**Le pays n'existe que sur les paiements par carte.** Les virements portent un IBAN, pas une
adresse — des dizaines de milliers de CHF n'ont donc pas de pays. Toute vue géographique doit être cadrée sur la
carte, sinon loyer et impôts sont mal attribués.

## L'app web

**Toute la navigation temporelle tient dans `?from=&to=&grain=`** ; sans paramètre,
le mois en cours. Pas d'état de
session, pas de fil caché : une fenêtre plus une granularité déterminent entièrement
la vue. Chaque niveau de zoom est donc une URL partageable, et le bouton retour du
navigateur fonctionne.

**Le fil d'ariane est reconstruit depuis la fenêtre**, pas accumulé. Si la fenêtre est
exactement un mois calendaire, il affiche « Tout › Année 2025 › Mai 2025 ». Une fenêtre
à cheval sur deux mois n'obtient pas de miette « mois » — c'est la réponse honnête
plutôt qu'un choix arbitraire.

**`annotate_chf` doit tourner une seule fois sur le ledger entier.** Elle met à l'échelle
les montants en devises contre l'ensemble des conversions de cette devise ; la relancer
sur une tranche donnerait des valeurs différentes pour la même transaction selon la
fenêtre consultée. D'où `Store` : le ledger est annoté au chargement, et chaque vue
n'est qu'un filtre sur ces mêmes objets.

**Le lien de zoom annonce ce qu'il fait vraiment.** Il passe la fenêtre à la même
logique `suggest_grain` que le reste de l'app, donc cliquer un mois descend directement
au jour, pas à la semaine. `charts.drill_target()` calcule la destination *et* le
libellé depuis le même appel — sinon l'infobulle promet un niveau que le clic ne livre pas.

**Les graphiques ont une seule implémentation**, dans `web/charts.py` : coordonnées
calculées en Python, SVG brut émis par le gabarit. Elle était auparavant scindée entre
`report.py` et le web ; c'est le genre de partage qui finit en deux copies divergentes de
la même arithmétique. Une seule surface, un seul endroit.

**Un panneau qui ne peut rien dire est absent.** `panels` dans
`views/dashboard._context` déclare la fenêtre minimale de chaque bloc — pas de
saisonnalité sur trois semaines, pas de comparaison annuelle sur une seule année.

**Une série s'arrête là où les données s'arrêtent.** Dans `year_chart`, les jours hors
de la plage observée valent `None`, pas 0 ni le dernier cumul : rembourrer les bords
ferait lire « n'a rien dépensé » ou « avait déjà dépensé ce total en août ».

**Le graphique temporel empile deux découpages du même argent.** `?stack=category`
(défaut) ou `?stack=bucket` : catégories, ou besoin/envie/épargne. Les colonnes gardent
exactement la même hauteur — c'est un seul jeu de données vu de deux façons, pas deux
graphiques. `charts.timeline()` reçoit donc un `source` (quelle ventilation empiler) et
un dictionnaire `fills` (la couleur de chaque tranche) plutôt que des indices de slot :
les buckets ont des couleurs fixes, pas un rang. Ce que `fills` ne nomme pas se replie
sur « Autres », ce qui garde les huit teintes validées.

Le mode vit dans l'URL comme le reste, et `dash_url()` (global Jinja) le fait suivre les
liens de période, de granularité, le fil d'ariane et le zoom. Il n'ajoute *que* cette
clé : réinjecter `request.args` entier propagerait `fragment=1` et casserait la parité
fragment / page complète.

**Tout fonctionne sans JavaScript.** Chaque contrôle est un vrai lien ou un vrai
formulaire ; `app.js` ne fait qu'échanger `<main>` en place au lieu de recharger. Le
test `test_fragment_and_full_page_agree` verrouille cette équivalence.

**`/previsions` est fragment-capable comme le dashboard.** Son contenu vit dans
`partials/previsions_main.html.j2`, servi seul sur `?fragment=1` : les boutons de vue
fiscale portent `data-nav` et le swap garde la position de défilement — changer de vue ne
remonte plus en haut de page. La garde du swap (`SWAPPABLE` dans app.js) accepte
`{"/", "/previsions", "/analyse"}`
(un `data-nav` ailleurs atterrirait sur une page sans fragment, dépouillée de son
enveloppe — `test_data_nav_only_points_at_fragment_capable_pages` le balaie sur les
quatre pages qui en portent). Le
handler de POST ignore les formulaires GET : sans ça, le select d'horizon serait POSTé
comme un no-op qui réécrirait `plans.json` pour rien.

**L'entête ne porte pas le nom du titulaire.** Il encombrait la barre pour rien : l'IBAN
identifie déjà le compte. Le nom reste dans le ledger (le parser le lit, le CLI
l'imprime) — il n'est plus rendu nulle part dans l'app, sauf comme contrepartie dans les
données elles-mêmes.

## Ce qui ne doit pas entrer dans le dépôt

Un fichier de catégorisation est une description très précise d'une vie. Les règles qui
nomment un **employeur, une régie, un praticien ou une personne** vivent donc dans
`data/local_rules.json` — gitignoré, au même titre que les relevés — et sont chargées
*avant* les règles publiques, qu'elles l'emportent donc. Ce qui reste dans
`categories.py` est du commerce public : Coop, SBB, Uber, Swisscom.

`data/local_rules.example.json` est l'exception versionnée : le format, sans les données.
Sans le fichier local, l'app tourne mais laisse ces bénéficiaires non catégorisés.

De même, aucune valeur identifiante en dur dans les tests : `test_cover_page_metadata`
vérifie la forme de l'IBAN, pas l'IBAN.

## Corrections manuelles

**`data/overrides.json` est séparé du ledger, et c'est le point.** Le ledger est de la
donnée dérivée : reconstruit depuis les PDF à chaque ingestion, il doit rester une copie
fidèle de ce que la banque a imprimé. Une catégorie éditée dedans serait perdue au
prochain import et brouillerait la frontière entre ce que la banque a dit et ce que
l'utilisateur a décidé.

Deux portées, volontairement distinctes :

- une **épingle** sur un mouvement, indexée sur `(référence, devise)` — la même identité
  que le ledger utilise pour dédoublonner, donc elle survit à la réimportation ;
- une **règle** sur un bénéficiaire, qui attrape ses mouvements passés *et futurs*. C'est
  celle qui rend la correction permanente.

Précédence, du plus faible au plus fort : règles statiques de `categories.py`, puis règles
apprises, puis épingles. Une épingle gagne toujours, pour qu'une exception ne se batte
jamais avec la règle de son propre bénéficiaire.

`Store._load` impose l'ordre : `classify_all` → `overrides.apply` → `annotate_chf` →
`buckets.annotate`. Inverser les deux premiers laisserait une transaction reclassée avec
le bucket de son ancienne catégorie.

Le reclassement en masse (« tout le filtre ») et la fusion de bénéficiaires par alias :
`docs/corrections.md`.

## Oublier un import

`Transaction.source` porte l'empreinte du PDF qui a apporté la ligne — posée à l'ajout,
jamais écrasée : une ligne déjà connue garde l'empreinte de son premier import. C'est ce
qui rend `--forget <sha256>` possible : retirer les lignes d'un import erroné et son
entrée du journal, sans reconstruire le ledger. Les lignes importées avant ce champ ne
portent rien et ne peuvent pas être oubliées individuellement ; les réimporter les tagge
pour la prochaine fois.

## Tests

**La suite tourne sans relevé.** Tout ce qui n'est pas le parser tourne sur
`statement`, un relevé inventé de bout en bout (`tests/synthetic.py`) mais de la même
forme que l'export réel : trois sections devises, EUR/USD clos à 0.00, jambes de
change à référence partagée et marge de ~1 %, lignes d'un jour hors ordre de
référence, un changement d'employeur, des factures saisonnières, un abonnement qui
s'arrête, une régie imprimée de deux façons, plusieurs caisses Coop. Une copie propre
du dépôt, sans `inbox/` ni `data/`, passe tout sauf les tests du parser. Avant, 272
tests sur 392 y étaient sautés : la couche web n'était testée que sur la machine qui
porte le relevé.

- Un test sur l'app prend `statement`, `ledger_file` ou `client` — jamais le vrai
  relevé. S'il lui faut une forme de données absente, l'ajouter à
  `tests/synthetic.py`, inventée, jamais recopiée du relevé réel.
- `real_statement` (le PDF d'`inbox/`) ne sert qu'à `test_parser.py` et à
  `test_real_data.py`, qui rend chaque page sur les vraies données et y vérifie les
  invariants : les cas limites que personne n'a pensé à inventer. Sautés sans le PDF.
- `test_browser.py` pilote `app.js` avec Playwright dans l'Edge ou le Chrome installé
  (aucun navigateur téléchargé) : infobulles, brush, échange de `<main>`, tri,
  recherche. C'est là que vivaient plusieurs bugs signalés ; chaque test a été
  vérifié en réintroduisant son bug. Sautés sans Playwright.
- `test_lint.py` fait tourner ruff avec des règles de bugs, pas de style
  (`pyproject.toml`) : un constat ruff est un test rouge. Il a trouvé à sa première
  passe un backspace invisible qui empêchait « Régie » de jamais correspondre.
- Un fichier de tests par page (`test_web_*.py`) ; la fixture `client` vit dans
  `conftest.py`, les helpers partagés dans `tests/webhelpers.py`.

## Invariants à préserver

- Aucune coordonnée ne doit atteindre le markup vide. Jinja rend `Undefined` en chaîne
  vide, donc une clé de géométrie manquante devient `x=""` — du markup valide qui ne
  dessine rien. Idem pour `var(--s)` : un slot non résolu ne peint aucune couleur. Trois
  tests balaient la page rendue pour ces deux formes.
- Toute option que `run.bat` transmet doit exister dans l'argparse de la CLI, sinon
  argparse sort en erreur avant d'avoir rien fait.

- `reconcile()` doit renvoyer une liste vide. C'est l'autotest du parser : une ligne perdue,
  scindée ou mal appariée casse la chaîne des soldes.
- `solde d'ouverture + net == solde de clôture`, au centime. Vérifié par les tests.
- Les huit couleurs catégorielles sont validées (contraste + daltonisme) dans les deux
  thèmes. Ne jamais en générer une neuvième : au-delà de 8, replier sur « Autres ».
- La déduplication doit rester idempotente : réimporter le même PDF n'ajoute rien.
- Le fragment et la page complète doivent rendre le même markup : ne pas réinjecter
  `request.args` tel quel dans `url_for` (ça propage `fragment=1` dans les liens).
- Les requêtes de filtrage doivent être annulables : sans ça une réponse ancienne et
  plus large peut écraser une plus récente.
- `data-nav` échange `<main>` avec un fragment du dashboard : ne jamais le poser sur un
  lien qui change de page, sinon la page arrive dépouillée de son enveloppe. Ni sur un
  lien qui télécharge un fichier : le navigateur s'en occupe seul.
- Le contenu large (tables, graphiques) défile dans sa propre boîte ; le corps de page ne
  doit jamais défiler horizontalement. L'en-tête est la seule rangée qui ne peut pas
  défiler en elle-même — c'est l'enveloppe — donc elle se resserre au lieu de déborder.
- La rampe du calendrier va du pâle au foncé dans les deux thèmes : **le plus foncé est
  le plus dépensier**. Une première version suivait la convention séquentielle inverse en
  thème sombre (la valeur haute s'éloigne du fond, donc s'éclaircit) ; à l'usage ça se lit
  « moins », et le sens s'inversait entre les thèmes. La convention a perdu.
- Corollaire : sur fond sombre, le palier le plus foncé frôle la luminance du fond, donc
  une journée sans dépense est dessinée **creuse** (contour, `--h0: transparent`). Une case
  vide remplie de gris se confondrait avec la journée la plus chargée ; un contour, jamais.
- Aucune donnée identifiante (IBAN, numéro de client, nom) ne doit être écrite en dur
  dans le code ou les tests : `test_cover_page_metadata` vérifie la *forme*, pas les
  valeurs. Le dépôt peut être publié.
- Les tests qui POSTent `/api/refresh` monkeypatchent `views.system.INBOX` vers un
  répertoire vide : si `inbox/` contenait de vrais PDFs, le ledger tmp serait réécrit
  avec de nouvelles transactions et d'autres tests se mettraient à échouer sans raison
  apparente.
- Toute requête qui écrit passe par `send()` dans app.js : elle vide le cache de
  préchargement. Un `fetch` d'écriture direct laisserait une vue préchargée revenir
  avec ses chiffres d'avant la correction.
- Un `popstate` qui ne change que le `#fragment` n'échange pas `<main>` : c'est un
  défilement, et l'échange refermait le panneau que l'ancre venait de déplier.
- Le reloader de Werkzeug ne surveille que les `.py`. Après un changement de `.j2`,
  redémarrer le serveur à la main — modifier un gabarit sans le faire laisse l'ancien
  rendu servi.

## Ce qui reste à faire

`ROADMAP.md` liste ce qui manque, avec une estimation d'effort par point ; au 02.10
le seul point ouvert est la sauvegarde de `data/`. L'app ne sert que sur laptop, en local : le glisser-déposer au doigt, le
durcissement serveur et l'ingestion automatique (watcher) sont déclarés hors
périmètre (section dédiée dans le ROADMAP), ne pas les reproposer.

## Conventions

- Code et commentaires en anglais ; interface en français.
- Pas de dépendance runtime dans le HTML : tout est inline, aucun CDN.
- Formatage suisse des nombres : apostrophe pour les milliers (`analysis.chf()`).
- `inbox/`, `data/` et `output/` sont gitignorés — données financières personnelles.
