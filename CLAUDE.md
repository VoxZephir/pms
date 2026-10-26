# PMS — analyse de relevés bancaires

Pipeline Python qui lit un relevé de transactions bancaire, le classe, et le rend
explorable dans une app web à navigation temporelle : Flask calcule et sert du JSON,
une app React (`frontend/`) met en page et dessine. Le parser livré est celui du
relevé PDF Swissquote, celui d'UBS a le sien (`ubs.py`) ; une autre banque se branche par un parser qui produit le même
`Statement` (section « Ajouter une banque ») ; le relevé ISO 20022 (camt.053) que la plupart
des banques suisses exportent a le sien (`camt.py`).

Il a existé un rapport HTML statique à côté. C'était un brouillon, il est supprimé, et il
ne doit pas revenir. Ne pas reproposer de le réintroduire — pour sortir des données, il y
a l'export CSV/xlsx.

## Lancer

```bash
run.bat                                  # ingestion + app Flask (défaut)
run.bat --test                           # la suite de tests
uv sync --extra web                      # .venv à jour selon uv.lock (outils de test compris)
uv lock                                  # après une modification des dépendances de pyproject.toml
.venv/Scripts/python -m pms              # ingestion + rapprochement des soldes
.venv/Scripts/python -m pms --check      # idem, sortie non nulle si un solde casse
.venv/Scripts/python -m pms --reparse    # relire aussi les PDF déjà importés
.venv/Scripts/python -m pms --status     # état du ledger et historique des imports
.venv/Scripts/python -m pms --forget <sha256>   # oublier un import erroné (sha vu dans --status)
.venv/Scripts/python -m pms --twint-report      # les Twint classés à la main, et le taux de juste des suggestions du tri
.venv/Scripts/python -m pms --finpension        # régénérer le snapshot 3a depuis inbox/finpension/
.venv/Scripts/python -m pms --capture c.json    # fusionner une capture d'épargne (skill /epargne)
.venv/Scripts/python -m pms --3a-value X --on AAAA-MM-JJ   # une valeur 3a lue dans l'app
.venv/Scripts/python -m pms --ibkr-journal      # l'export de transactions IBKR d'inbox/ibkr/
.venv/Scripts/python -m pms --crypto            # relevé crypto Revolut (inbox/revolut/crypto/), valorisé jour par jour
.venv/Scripts/python -m pms --crypto --crypto-qty ETH=0.5,SOL=10   # idem, staking calé sur l'app
.venv/Scripts/python -m pms --benchmarks        # indices de référence publics (S&P 500, Nasdaq, or…) en CHF, dividendes réinvestis
.venv/Scripts/python -m pms --backup [DOSSIER]  # zip chiffré de data/ + inbox/ (défaut OneDrive/PMS-sauvegardes), run.bat le lance
.venv/Scripts/python -m pms --restore ARCHIVE [--into DOSSIER]   # déchiffrer une sauvegarde, sans rien écraser
.venv/Scripts/python -m pms --ibkr              # IBKR depuis le service Flex (data/ibkr_flex.json), sans connecteur
.venv/Scripts/python -m pms --refresh --daily   # IBKR, repères, indices du 3a, crypto, inflation : run.bat, une fois par jour
.venv/Scripts/python -m pms --export out.xlsx   # ou out.csv
.venv/Scripts/python -m pms --redact r.pdf      # caviarder (IBAN, noms, adresses) vers output/caviarde/ ; caviarder.bat
.venv/Scripts/python -m pms --from 2025-01-01 --to 2025-12-31
.venv/Scripts/python -m pms.web          # app Flask (127.0.0.1 ; le téléphone passe par `tailscale serve`) ; ramasse les relevés téléchargés (--no-watch)
.venv/Scripts/python -m pytest tests -q  # ~3 min, ruff, build du front et navigateur compris
.venv/Scripts/python -m ruff check src tests
cd frontend && npm install               # une fois : seulement pour modifier l'interface
cd frontend && npm run build             # types vérifiés, build dans src/pms/web/static/spa/ — à commiter
cd frontend && npm run dev               # rebuild à chaque sauvegarde ; recharger la page suffit
cd frontend && npm test                  # Vitest
```

**Le build du front est commité** (`src/pms/web/static/spa/`) : `run.bat` tourne sans
Node. Toute modification de `frontend/src/` est suivie de `npm run build` et du commit du
dossier construit ; `tests/test_frontend.py` refait le build à côté et échoue si les
noms d'assets diffèrent.

**Les dépendances passent par uv** : `uv.lock` fixe les versions exactes, `.python-version`
celle de Python, et `run.bat` installe uv puis lance `uv sync` (sans le groupe `dev`,
sauf avec `--test`). Une dépendance ajoutée à `pyproject.toml` est suivie de `uv lock`
et du commit de `uv.lock`, sinon `uv sync --locked` refuse de démarrer. Le paquet est
installé en éditable, donc pas de `PYTHONPATH` à positionner. Si un import échoue,
relancer `uv sync --extra web`.

**Un PDF déjà importé n'est pas relu.** L'empreinte est comparée au journal des
imports *avant* le parsing — c'est le parsing qui coûte (14 s pour un relevé de deux
ans), et chaque lancement le repayait pour chaque PDF resté dans `inbox/` : 17 s pour
trois relevés déjà connus, 0,6 s depuis. `--reparse` force la relecture, pour
confronter les lignes stockées à un parser modifié (un écart est signalé en
conflit, jamais écrasé).

## Architecture

```
                                                     ┌─▶ export ──▶ *.csv / *.xlsx
inbox/ ─▶ banks ─▶ parser ─▶ ledger.json ─▶ categories ┤
                   revolut       │          analysis ──┴─▶ web/api ─JSON─▶ frontend (React)
                      │          │          buckets                         http://127.0.0.1:5000
                 reconcile()   gaps()
```

| Module | Rôle |
|---|---|
| `models.py` | `Transaction`, `AccountSummary`, `Statement` |
| `banks.py` | registre des banques : quel parser lit quel export d'`inbox/`, comment chacune reconnaît le sien (`recognise`), où le chercher |
| `intake.py` | un export dans `inbox/` et le ledger, ou refusé avec la raison ; `LOCK` sérialise toutes les ingestions du serveur |
| `parser.py` | PDF Swissquote → transactions, par géométrie ; `reconcile()` valide (par compte et devise) |
| `revolut.py` | export CSV Revolut → le même `Statement`, compte secondaire `revolut` |
| `ubs.py` | l'export PDF « Account transactions » d'UBS (anglais) → le même `Statement`, par géométrie ; 500 mouvements au plus par export (`docs/releves.md`) |
| `camt.py` | relevé ISO 20022 camt.053 (XML) → le même `Statement` : la plupart des banques suisses, un seul parser ; le solde d'une ligne est calculé depuis l'ouverture du relevé, la clôture imprimée sur sa dernière ligne (`docs/releves.md`) |
| `crypto.py` | relevé crypto Revolut → la poche « Crypto » : quantités jour par jour, flux, valeur aux cours publics figés (`data/crypto.json`, `--crypto`) |
| `benchmarks.py` | catalogue d'indices de référence publics en CHF, dividendes réinvestis (`data/benchmarks.json`, `--benchmarks`), choisis dans l'URL (`?bench=`) |
| `ai.py` | l'assistant, tenu court : fournisseur et modèle (choisis dans la page Assistant, `data/ai.json` : Claude, DeepSeek ou Ollama), clé par fournisseur, schéma de réponse, chiffres vérifiés contre les faits, noms masqués, journal et cache |
| `assist/` | un module par tâche de l'assistant (`merchants`, `month`, `savings`, `questions`, ce qu'elles partagent dans `common`) : ce que chacune de l'assistant envoie et ce qui est fait de sa réponse : catégories des commerçants, revue en mots, « pourquoi ce mois », l'épargne en mots, question en français |
| `twint.py` | les suggestions du tri des Twint, apprises des Twint déjà classés et mesurées sur eux (`--twint-report`) |
| `fiscal.py` | plafond 3a de l'année et lacunes, fortune au 31.12 compte par compte, revenus IBKR de l'année |
| `backup.py` | copie zippée et chiffrée de `data/` et `inbox/` hors du disque (`--backup`), écrite seulement si quelque chose a changé ; `--restore` |
| `refresh.py` | ce qui bouge sans relevé, rafraîchi étape par étape (IBKR, repères, inflation, crypto) : `run.bat` une fois par jour, le bouton « Rafraîchir » d'Épargne (`web/api/fetch.py`) ; `data/refresh.json` |
| `flex.py` | le service Flex d'IBKR → `data/ibkr.json`, en n'ajoutant que le plus récent (`--ibkr`) |
| `allocation.py` | allocation cible par classe d'actifs, `data/allocation.json`, et l'écart en francs |
| `ledger.py` | accumulation multi-imports, déduplication, détection de trous |
| `categories.py` | règles marchand → catégorie/sous-catégorie |
| `analysis.py` | agrégations, conversion CHF, coûts custodian, récurrence, géographie, **découpage par période et séries à granularité variable** |
| `lookback.py` | la page Analyse au-delà du profil : mois entiers, un an contre l'autre par catégorie, régularité, rythme du mois, jours de la semaine, une catégorie de près |
| `upcoming.py` | la page À venir : les engagements lus dans les paiements (rythme et montant réguliers), leurs prochaines dates, leurs hausses de prix, les délais pour les changer |
| `health.py` | la franchise LAMal rejouée : part à charge selon la loi, primes au rabais maximal, frais de santé relus depuis la part payée ; `data/health.json` |
| `weekly.py`, `notify.py` | le résumé de la semaine (catégories et montants, jamais un nom) et son envoi au téléphone par ntfy, une fois par semaine depuis le processus qui sert ; `data/notify.json` |
| `projects.py` | les projets : des mouvements rassemblés sous un nom, au coût net (dépensé moins remboursé), les voyages proposés depuis les séjours à l'étranger ; `data/projects.json` |
| `taxes.py` | la page Impôts : chaque rubrique de la déclaration que le relevé renseigne (3a, primes, frais de maladie, dons, transports, formation), la règle fédérale qui en fait une déduction, les lignes derrière |
| `holdings.py` | les titres hors relevé (une action non cotée) : valeur fiscale déclarée par année, dividende retrouvé dans le relevé et ramené au brut (impôt anticipé de 35 %) ; `data/holdings.json` |
| `retro.py` | le bilan de l'année : une douzaine de constats (mois le plus cher et pourquoi, habitudes, pays, pause la plus longue) |
| `freedom.py` | l'indépendance financière : années de dépense couvertes, objectif à un taux de retrait, date au rendement déclaré |
| `cpi.py` | l'indice des prix tenu à jour par `--refresh` : une série publiée n'est gardée que si elle redonne les mois connus ; `data/cpi.json` |
| `swiss.py` | contre la Suisse : l'inflation de son panier fixe contre l'indice des prix, son mois contre le ménage suisse moyen ; chiffres de l'OFS copiés avec leur source |
| `tidy.py` | la page Corrections : part de la dépense classée, fusions proposées (une enseigne imprimée de plusieurs façons) |
| `buckets.py` | Need / Want / Save, et leurs parts mois par mois |
| `review.py` | revue du mois : ce qui a changé par rapport à l'historique |
| `export.py` | CSV et xlsx de la vue courante ; écrivain OOXML sans dépendance |
| `redact.py` | caviarder un PDF hors de l'app : IBAN, noms (titulaire, contreparties, personnes), adresses retirés du fichier, relu après coup (`--redact`, `caviarder.bat`) |
| `plans.py` | suggestions de ponctuels saisonniers, `data/plans.json` (plans entiers sous un nom : les scénarios), projection de trésorerie |
| `budgets.py` | objectifs mensuels par catégorie, `data/budgets.json`, jauges dans le panneau mensuel |
| `finpension.py` | journal CSV + rapports de performance du 3a, `data/finpension.json` |
| `ibkr.py` | lit `data/ibkr.json` — l'épargne hors relevé (Interactive Brokers), snapshot figé |
| `ibkr_history.py` | l'export « Transaction History » d'IBKR : versements, frais, positions depuis l'ouverture du compte, valeur reconstruite chaque semaine (`--ibkr-journal`) |
| `snapshots.py` | fusionne une capture d'épargne sans réécrire l'historique (`--capture`), dit où s'arrête chaque série (`--status`) |
| `web/store.py` | charge le ledger une fois, sert des vues par période |
| `web/guard.py` | qui peut parler à l'app : Host de cette machine, écriture de même origine, écoute sur loopback ou le tailnet |
| `web/compress.py` | gzip du texte servi (HTML, CSS, JS, JSON, CSV) : ce que le téléphone télécharge, divisé par 5 |
| `web/updates.py` | le bouton « Mettre à jour » : `git fetch` au plus une fois l'heure, `git pull --ff-only`, redémarrage ; une dépendance changée demande de relancer `run.bat` |
| `web/watcher.py` | les Téléchargements surveillés : un relevé téléchargé sur le PC est ingéré dans la minute |
| `web/periods.py` | résolution de fenêtre, préréglages, fil d'ariane |
| `web/palette.py` | les huit teintes catégorielles : quelle catégorie prend quel slot, le reste replié sur « Autres » |
| `web/news.py` | le relevé qui vient d'arriver (annonce, mois d'arrivée) et celui qui est en retard |
| `web/api/` | l'API JSON, un module par page (`shell` : période et méta ; `dashboard`, `transactions`, `savings`, `previsions`, `analyse`, `corrections`, `imports`, `assist/` : l'assistant, un module par usage) ; sert aussi l'app React sur chaque chemin de page, et redirige les anciennes adresses |
| `web/views/` | le reste des routes : `common` (blueprint, store, modes d'URL, filtre et tri de la table), `corrections` (`/api/reclassify*`, tri des Twint), `previsions` (projection, actions sur le plan), `savings` (arithmétique du panneau Épargne, sans route ; `savings_reads` : cascade, mois par mois, baisses), `exports` (CSV, xlsx), `system` (santé, réingestion, redémarrage) |
| `frontend/` | l'app React (Vite, TypeScript, Tailwind) : `shell/` (coquille, période, palette), `pages/`, `charts/` (la géométrie de tous les graphiques — l'unique implémentation), `components/`, `lib/` (API, URL comme état, formats) |

## Où lire avant de toucher

Le raisonnement détaillé de chaque fonctionnalité vit dans `docs/`, pas ici : ce
fichier est chargé à chaque session, eux seulement quand on y travaille. Lire le bon
**avant** de modifier — chaque décision y est justifiée, et la plupart ont été prises
contre une première version qui semblait évidente.

| Avant de toucher | Lire |
|---|---|
| `plans.py`, `/previsions`, `views/previsions.py`, la courbe de patrimoine, le rendement par année et par poche, `freedom.py` | `docs/previsions.md` |
| `/analyse`, `lookback.py`, `swiss.py`, `cpi.py`, le panneau « Dépenses par mois » et ses budgets, `plans.monthly_profile` | `docs/analyse.md` |
| `frontend/`, `web/api/`, l'état dans l'URL, les graphiques, le sommaire et « Haut de page », le téléphone, le bouton ⟳, le brush, les panneaux repliés, les panneaux « Engagements sans passage récent », « D'où vient l'argent » et « Évolution des parts » | `docs/app-web.md` |
| le panneau Épargne, le bouton « Rafraîchir », `refresh.py`, `ibkr.py`, `flex.py`, `finpension.py`, `snapshots.py`, `crypto.py`, `benchmarks.py`, `fiscal.py`, `allocation.py`, `views/savings.py`, `views/savings_reads.py`, la skill `/epargne` | `docs/epargne.md` |
| `export.py`, les routes d'export, l'écrivain xlsx | `docs/export.md` |
| le reclassement en masse, les alias de bénéficiaires, le tri des Twint (`/corrections/tri`), `tidy.py`, les filtres (dont le compte, `?acct=`) et le résumé de `/transactions` | `docs/corrections.md` |
| `ai.py`, `assist/`, `twint.py`, `web/api/assist/`, `components/assist/`, tout ce qui appelle un modèle de langage | `docs/assistant.md` |
| `review.py`, le panneau « Revue du mois » | `docs/review.md` |
| `web/guard.py`, `web/compress.py`, `web/__main__.py`, `/importer`, Tailscale, le manifest | `docs/acces-distant.md` |
| `backup.py`, `--backup`, `--restore`, la clé `data/backup.key` | `docs/sauvegarde.md` |
| `upcoming.py`, `health.py`, `/a-venir`, le panneau « À venir » du tableau de bord | `docs/a-venir.md` |
| `retro.py`, `/bilan`, la barre latérale et son groupe « Plus » | `docs/bilan.md` |
| `weekly.py`, `notify.py`, le résumé poussé, les virements à soi-même (`categories.is_to_self`) | `docs/semaine.md` |
| `projects.py`, `/projets`, le choix du projet dans la fiche d'une transaction | `docs/projets.md` |
| `taxes.py`, `holdings.py`, `/impots`, `fiscal.py` côté déclaration, les règles de catégorie qui ne lisent pas l'adresse | `docs/impots.md` |
| `redact.py`, `--redact`, `caviarder.bat`, `/caviarder` | `docs/caviardage.md` |
| `intake.py`, `web/watcher.py`, `banks.recognise`, `ubs.py`, le rappel de relevé en retard, `camt.py`, le relevé d'un autre titulaire | `docs/releves.md` |

## Ajouter une banque

Le README invite les utilisateurs d'une autre banque à te demander d'adapter le code à
leur relevé. Quand on te le demande : lire le relevé déposé dans `inbox/` (son format,
ses colonnes, son vocabulaire), écrire le parser, le brancher, puis prouver qu'il est
juste avec `reconcile()` sur ce vrai relevé — pas seulement des tests verts. Ne jamais
recopier une ligne, un nom ou un IBAN de ce relevé dans le code, les tests ou la doc :
les formes manquantes vont dans `tests/synthetic.py`, inventées.

Le contrat complet, champ par champ, est dans `README.md` (« Brancher une autre
banque ») — c'est aussi la doc des contributeurs. L'essentiel pour ne pas le casser :

- **Un parser = une fonction `parse(path) -> Statement`**, déclarée dans
  `banks.SOURCES` avec le dossier d'`inbox/` où ses exports sont déposés.
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
- **Un compte secondaire** porte `Transaction.account` (`""` = le compte principal,
  celui dont l'IBAN nomme le ledger). Tout ce qui lit un solde passe par
  `analysis.cash_points` / `closing_chf` (somme des comptes) ; `gaps()` et
  `reconcile()` chaînent par (compte, devise). Ne jamais relire `t.balance` d'une
  devise sans le compte : 30 CHF de Revolut après 10'000 de Swissquote ne sont pas une
  rupture de 9'970.
- **Un virement entre ses propres comptes** est `categories.INTERNAL` des deux côtés,
  et `analysis.is_internal` le sort des dépenses comme des revenus. L'invariant
  « ouverture + revenus − dépenses = clôture » d'un compte compte donc ses virements
  internes (`test_chf_conversion_ties_out_to_the_closing_balance`).
- **Les lignes d'un compte secondaire antérieures au compte principal** restent dans
  le ledger, hors analyse (`ledger.primary_start`).

**Revolut (`revolut.py`).** L'export fr-ch est de l'UTF-8 encodé deux fois (« Ã©tat »).
La chaîne des soldes tient dans l'ordre du fichier, qui suit la date de *fin*
(comptabilisation), jamais celle de début : une ligne est datée de sa fin. Le frais
s'ajoute au montant (`Solde = précédent + Montant − Frais`). Pas de colonne de
référence : elle est dérivée du contenu de la ligne, les deux jambes d'un change
partagent la leur. Les blocages « RENVOYÉ » ne sont pas des mouvements.

**Le relevé crypto Revolut perd la virgule des quantités** (0.01234567 ETH s'imprime
« 1,234,567 »). Une transaction porte aussi prix et valeur : la quantité est retrouvée
en plaçant la virgule au plus près de valeur / prix — exacte. Une récompense de staking
n'a pas de prix : sa virgule est placée au plus près de la récompense attendue (staké ×
rendement × jours écoulés, le rendement ajusté sur les récompenses elles-mêmes) — selon
la monnaie, tout sort net ou ~1 récompense sur 7 reste ambiguë d'un facteur 10 ; `--crypto-qty` cale le
total sur l'app. La crypto est une poche comme les autres (total, TWR/MWR, courbe,
risque) : cours Binance quotidiens × change BCE, figés à la capture. **Le cash de
l'épargne compte les soldes EUR/GBP** (`analysis.cash_points` avec un taux) : un achat
crypto payé en euros Revolut sortait sinon du cash sans y avoir été compté, et se lisait
comme un gain du total.

## Faits établis sur le relevé Swissquote (à ne pas re-découvrir)

**Le PDF.** Trois sections devises qui se suivent (CHF, puis EUR, puis USD) ; un export
de deux ans fait une centaine de pages et quelques milliers de transactions.

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

**La colonne « Frais et taxes » est vide sur toutes les pages.** Swissquote ne facture aucune
commission explicite sur ce compte. Ne pas chercher les frais là.

**Le coût réel du custodian est la marge de change.** Chaque conversion imprime un taux de
référence *et* le montant CHF réellement débité, et les deux ne concordent pas : l'écart
vaut 0.97 % (médiane), très stable d'une conversion à l'autre. C'est une marge
tarifaire, pas un aléa de marché.

**La clé d'identité d'un mouvement est `(référence, devise)`, pas la référence seule.** Une
conversion imprime la *même* référence sur ses deux jambes (débit CHF et crédit EUR/USD) :
il y a autant de références distinctes en moins que de lignes qu'il y a de conversions.

**La banque n'ordonne pas les lignes d'un même jour par référence** (un jour donné, elle
imprime une référence plus haute avant une plus basse). D'où le champ `Transaction.seq` : la position de la ligne au
sein de sa propre date. Trier par `(date, référence)` fabrique des ruptures de solde
fantômes sur chaque journée concernée.

**Les transferts de change sont des mouvements internes, pas des dépenses.** Compter à la
fois la jambe CHF et l'achat en devise double-compterait. Les comptes EUR et USD ouvrent et
ferment à 0.00 exactement, ce qui rend le calcul exact : la somme des jambes CHF *est* le
coût en francs de toutes les dépenses en devises.

**Le bucket `Save` n'a que peu de lignes : des virements vers Interactive Brokers, et
parfois un retrait qui en revient** (la ligne du retrait nomme le titulaire, seul le BIC
`IBKRUS33` dit IBKR). Le compte IBKR peut être plus ancien que le relevé — son
historique complet vient de l'export CSV, pas du connecteur (un an seulement), et
`docs/epargne.md` le détaille ; un 3a alimenté hors du relevé n'y apparaît pas non plus.
L'épargne affichée est donc presque entièrement du solde non dépensé : `buckets.summarise()` sépare `Versé` de `Non dépensé`.
Un tel virement est aussi un **versement IBKR** : il n'est pas de la performance
(`ibkr.flows`, `docs/epargne.md`) — ne jamais recalculer un rendement IBKR comme le
rapport de deux NAV. La part non dépensée est dessinée
**creuse** dans la barre et n'est pas cliquable — elle n'a aucune transaction derrière elle,
un lien tomberait sur une table vide.

**Un Twint envoyé n'imprime que « Paiement Twint ».** Ni bénéficiaire, ni message, ni
lieu : des centaines de lignes dont seul le montant et la date sont connus. Elles sont « Twint non
identifié », pas « Transferts P2P » (Twint paie aussi des parcmètres), et ne se classent
qu'à la main — `/corrections/tri`. Aucune règle ni aucun modèle de langage ne lit une
catégorie sur cette ligne, et l'app TWINT n'offre pas d'export. Ce que le tri propose est
appris des Twint que le titulaire a déjà classés (`twint.py`), mesuré sur eux, montré avec
ce taux, jamais appliqué : `docs/assistant.md`. **Convention du titulaire (17.10) :** un
Twint qui rembourse une part de quelque chose se classe selon ce que l'argent a payé —
une part de voyage en « Loisirs & voyages », pas en « Transferts P2P » ; le tri le
rappelle sur un Twint de 100 CHF ou plus autour d'un séjour à l'étranger.

**Le pays n'existe que sur les paiements par carte.** Les virements portent un IBAN, pas une
adresse — une grande part de l'argent n'a donc pas de pays. Toute vue géographique doit être cadrée sur la
carte, sinon loyer et impôts sont mal attribués.

## L'app web

**Flask calcule, React dessine.** Chaque page a son endpoint JSON (`web/api/`) qui porte
des chiffres déjà justes : agrégats, conversions, projections, slots de couleur. Le
navigateur ne refait aucune arithmétique financière ; il met en page, et calcule la
seule géométrie des graphiques, à la largeur de l'écran. Les mêmes chemins (`/`,
`/transactions`, `/epargne`, `/a-venir`, `/projets`, `/impots`, `/bilan`, `/analyse`, `/previsions`, `/corrections`, `/importer`,
`/caviarder`, `/jour/<date>`) servent l'app ; les anciennes adresses (`/reclasser`, `/day/…`, `/app/…`)
redirigent. Le détail : `docs/app-web.md`.

**Toute la navigation temporelle tient dans `?from=&to=&grain=`** ; sans paramètre,
le mois en cours. Pas d'état de session, pas de store côté client : une fenêtre plus une
granularité déterminent entièrement la vue. Chaque niveau de zoom est donc une URL
partageable, et le bouton retour du navigateur fonctionne. `lib/url.ts` dit quelles clés
suivent : la fenêtre d'une page à l'autre (`WINDOW_KEYS`), les bascules de vue
(`stack`, `perf`, `bench`…) d'une période à l'autre (`VIEW_KEYS`), les filtres de la
table seulement dans la table (`TABLE_KEYS`). Une clé propre à une page ne fuit jamais
dans les liens d'une autre.

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
au jour, pas à la semaine. `api/dashboard.drill_target()` calcule la destination *et* le
libellé depuis le même appel — sinon l'infobulle promet un niveau que le clic ne livre pas.

**Les graphiques ont une seule implémentation**, dans `frontend/src/charts/` : colonnes
(`Columns`), courbes (`Lines`), calendrier (`Calendar`). Elle a d'abord été scindée entre
`report.py` et le web, puis a vécu dans `web/charts.py` ; c'est le genre de partage qui
finit en deux copies divergentes de la même arithmétique. Une seule surface, un seul
endroit.

**Un panneau qui ne peut rien dire est absent.** `panels` dans `api/dashboard`
déclare la fenêtre minimale de chaque bloc — pas de saisonnalité sur trois semaines, pas
de comparaison annuelle sur une seule année.

**Une série s'arrête là où les données s'arrêtent.** Dans le cumul année par année
(`Years`), les jours hors de la plage observée valent `null`, pas 0 ni le dernier cumul :
rembourrer les bords ferait lire « n'a rien dépensé » ou « avait déjà dépensé ce total en
août ». `Lines` coupe la ligne sur un `null`.

**Le graphique temporel empile deux découpages du même argent.** `?stack=category`
(défaut) ou `?stack=bucket` : catégories, ou besoin/envie/épargne. Les colonnes gardent
exactement la même hauteur — c'est un seul jeu de données vu de deux façons, pas deux
graphiques. L'API envoie les deux ventilations et la couleur de chaque tranche (slots des
catégories, `bucket_fill` fixe des buckets) ; ce qui n'a pas de slot se replie sur
« Autres », ce qui garde les huit teintes validées.

**Une écriture passe par `send()`** (`lib/api.ts`) : elle invalide toutes les requêtes en
cache, puis la vue se recharge avec les chiffres d'après la correction. Les corrections
s'annulent depuis le toast qui les confirme.

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
jamais avec la règle de son propre bénéficiaire — sauf sur la ligne même depuis laquelle
on pose la règle : celle-là cède la partie de son épingle que la règle contredit
(`yield_to_rule`). Annuler rétablit l'état d'avant (`snapshot`/`restore`), pas « rien ».

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
  `test_real_data.py`, qui interroge chaque endpoint de l'API sur les vraies données et
  y vérifie les invariants : les cas limites que personne n'a pensé à inventer. Sautés
  sans le PDF.
- Les tests d'une page interrogent son API (`webhelpers.api`, qui refuse un NaN dans le
  JSON) : ils vérifient des chiffres, pas du markup.
- `test_browser.py` pilote l'app construite avec Playwright dans l'Edge ou le Chrome
  installé (aucun navigateur téléchargé), au bureau et à 390 px au doigt : aucune page
  ne lève d'erreur ni ne défile de côté, infobulles, zoom, brush, flèches, recherche,
  tri, reclassement et annulation, palette, thème, onglets et feuille de période du
  téléphone, double toucher. Sautés sans Playwright.
- `test_frontend.py` lance `tsc` et Vitest, puis refait le build dans un dossier
  temporaire et le compare au build commité. Sautés sans Node.
- `test_lint.py` fait tourner ruff avec des règles de bugs, pas de style
  (`pyproject.toml`) : un constat ruff est un test rouge. Il a trouvé à sa première
  passe un backspace invisible qui empêchait « Régie » de jamais correspondre.
- Un fichier de tests par page (`test_web_*.py`) ; la fixture `client` vit dans
  `conftest.py`, les helpers partagés dans `tests/webhelpers.py`.

## Invariants à préserver

- Aucun NaN ni slot non résolu ne doit atteindre le navigateur. Un NaN dans le JSON
  casse `JSON.parse` côté client (`encode.jsonable` le rend `null`, `webhelpers.api` le
  refuse) ; un `var(--s8)` ne peint aucune couleur — une couleur se prend d'un slot que
  l'API a donné, ou se replie sur `--unsorted`.
- Toute option que `run.bat` transmet doit exister dans l'argparse de la CLI, sinon
  argparse sort en erreur avant d'avoir rien fait.

- `reconcile()` doit renvoyer une liste vide. C'est l'autotest du parser : une ligne perdue,
  scindée ou mal appariée casse la chaîne des soldes.
- `solde d'ouverture + net == solde de clôture`, au centime. Vérifié par les tests.
- Les huit couleurs catégorielles sont validées (contraste + daltonisme) dans les deux
  thèmes. Ne jamais en générer une neuvième : au-delà de 8, replier sur « Autres ».
- La déduplication doit rester idempotente : réimporter le même PDF n'ajoute rien.
- Une requête se range sous la clé de son URL (TanStack Query) : une réponse ancienne et
  plus large ne peut pas écraser une plus récente, et `keepPreviousData` garde la vue
  précédente à l'écran pendant le chargement plutôt qu'un squelette.
- Un lien qui télécharge un fichier (`/export.xlsx`…) est un `<a href>` ordinaire, hors
  du routeur : le navigateur s'en occupe seul.
- Le contenu large (tables, graphiques) défile dans sa propre boîte ; le corps de page ne
  doit jamais défiler horizontalement, à 390 px comme au bureau. Un enfant de grille ou
  de flex qui contient du texte long prend `min-w-0` (`Card` le porte), sinon il pousse
  la page de côté — `test_browser.py` le vérifie sur chaque page.
- Le build commité (`src/pms/web/static/spa/`) correspond aux sources de `frontend/` :
  `npm run build` après toute modification, et le commit du dossier construit avec.
- Les surfaces (`--surface`, en clair et en sombre) et les huit teintes de
  `frontend/src/styles.css` sont celles qui ont été validées ; ne pas les retoucher sans
  refaire la validation.
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
- Toute requête qui écrit passe par `send()` (`lib/api.ts`) : elle invalide le cache des
  requêtes. Un `fetch` d'écriture direct laisserait une vue en cache revenir avec ses
  chiffres d'avant la correction.
- Un seul bouton `primary` par formulaire : l'action pour laquelle il existe (Appliquer,
  Enregistrer, Ajouter). Les actions de ligne d'un tableau restent `size="sm"`, et un
  libellé au-dessus d'un chiffre prend la voix `.eyebrow` (tuiles, héros, cartes).
- `index.html` de l'app est servi `no-cache`, les assets (noms hachés) `immutable` : un
  nouveau build se voit au rechargement suivant, sans qu'un ancien JS reste en cache.
- Le reloader de Werkzeug ne surveille que les `.py` ; le build du front est relu à
  chaque requête, donc un `npm run build` se voit en rechargeant la page.
- L'app n'a pas de connexion : ce qui la protège est `web/guard.py`. Le serveur écoute
  sur `127.0.0.1` (ou une adresse Tailscale), jamais `0.0.0.0` ni le réseau local ;
  `--debug` seulement sur loopback. Une route qui écrit n'a rien à faire contre le CSRF :
  la garde d'Origin s'en charge pour toutes. Un test qui POSTe avec un en-tête Origin
  doit donner celui de l'app (`http://localhost` sous le client de test).
- Toute ingestion faite par le serveur passe par `intake.LOCK` ; un fichier entré par
  l'import ou la surveillance passe par `intake.take`, qui le retire d'`inbox/` si son
  parser n'en tire rien. La surveillance ne touche à rien dans Téléchargements qu'une
  banque ne reconnaisse à son contenu (`banks.recognise`), et ne tourne que dans le
  processus qui sert — jamais dans le superviseur du reloader, ni sous `create_app` (la
  suite de tests n'en démarre aucune).
- Les gestes passent par les pointer events, jamais `mouse*` seuls : souris, stylet et
  doigt sont le même code. `touch-action` se pose sur le `<svg>`, pas sur ses formes
  (Chrome l'y ignore) : `touch-pan-y` laisse le glissement vertical à la page et donne le
  glissement latéral au graphique (brush, lecture point par point). Au doigt, un premier
  toucher lit une colonne, un second l'ouvre.

## Ce qui reste à faire

`ROADMAP.md` liste ce qui manque ; au 20.10 un point est ouvert : une autre banque sans
parser écrit à la main (le modèle écrit une recette du format, l'app l'applique et
`reconcile()` la vérifie). L'app se lit sur le téléphone par Tailscale
(`docs/acces-distant.md`), un relevé téléchargé sur le PC entre tout seul
(`docs/releves.md`), l'interface est en React (`docs/app-web.md`). Depuis le 19.10 elle
regarde aussi devant et autour : À venir, Impôts (le canton se choisit sur la page), Projets, le
résumé de la semaine poussé par ntfy, le bilan de l'année, l'indépendance financière et
la comparaison à la Suisse. Le travail se fait sur `main` ; le bouton « Mettre à jour »
suit `main` (`web/updates.py`). Reste hors périmètre (section dédiée dans le ROADMAP), à ne
pas reproposer : l'exposition publique (VPS, port ouvert, `tailscale funnel`) avec la
connexion applicative qu'elle exigerait. Aller chercher le relevé chez la banque reste
manuel, et le restera (pas d'API Swissquote, pas d'agrégateur tiers).

## Conventions

- Code et commentaires en anglais ; interface en français.
- Ne jamais donner d'estimation d'effort en jours de travail (ni dans une réponse, ni
  dans le ROADMAP, ni dans une maquette) : l'utilisateur les juge imprécises et inutiles.
- Aucun CDN : le JS, le CSS et la police sont dans le build servi par Flask. L'app
  marche sur le tailnet sans rien demander à un tiers.
- Formatage suisse des nombres : apostrophe pour les milliers (`analysis.chf()`).
- `inbox/`, `data/` et `output/` sont gitignorés — données financières personnelles.
  `--backup` refuse un dossier de destination dans le dépôt : une copie des relevés y
  serait à un `git add -A` d'être publiée.
- Les clés de l'assistant (`data/ai.<fournisseur>.key`) suivent la même règle que le
  jeton Flex : jamais imprimées, jamais dans un message d'erreur, dans
  `data/ai_log.jsonl` ni dans une réponse de l'API, jamais demandées. Le modèle se
  choisit dans l'app (page Assistant) ; la clé reste un fichier.
  Un modèle de langage ne calcule aucun chiffre affiché : il met en mots des faits
  calculés par Flask, et un texte qui cite un nombre absent de ces faits est écarté
  (`ai.checked_text`). Rien ne s'écrit sur sa seule réponse : toujours un clic, annulable.
- Le jeton Flex d'IBKR (`data/ibkr_flex.json`) n'est jamais imprimé, jamais mis dans
  un message d'erreur, jamais demandé à l'utilisateur : il le pose lui-même dans le
  fichier.
- La clé des sauvegardes (`data/backup.key`) n'est jamais imprimée ni mise dans une
  archive ; la CLI nomme le fichier, l'utilisateur en garde une copie dans son
  gestionnaire de mots de passe.
