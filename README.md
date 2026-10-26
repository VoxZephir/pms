# Analyse de relevés bancaires

Lit un relevé de transactions bancaire, catégorise les dépenses, chiffre ce que la
banque a prélevé, et le rend explorable dans une app web locale.

Deux banques sont livrées : le relevé PDF de **Swissquote** (le compte principal) et
l'export CSV de **Revolut**, qui se lisent ensemble dans le même ledger. Toute autre
banque se branche en écrivant un seul module — voir
[Brancher une autre banque](#brancher-une-autre-banque) : le ledger, la catégorisation,
l'analyse et l'app ne connaissent que le modèle commun.

## Démarrage

Lancez `run.bat` : sans relevé, l'app s'ouvre dans le navigateur sur un accueil qui propose
d'en importer un. Ou déposez votre relevé dans `inbox/` — le PDF Swissquote à la racine, l'export Revolut
(Relevé → CSV) dans `inbox/revolut/`, le relevé ISO 20022 (camt.053, XML) de la plupart
des banques suisses — PostFinance, UBS, Raiffeisen, banques cantonales — dans `inbox/camt/` — puis :

```bash
run.bat
```

Rien à installer avant : au premier lancement, le script installe [uv](https://docs.astral.sh/uv/),
qui installe la bonne version de Python et les dépendances aux versions exactes de
`uv.lock`. Il ingère ensuite les relevés de `inbox/`, puis démarre l'app sur http://127.0.0.1:5000.

Ensuite, plus besoin de passer par `inbox/` : tant que l'app tourne, un relevé téléchargé
dans le dossier Téléchargements est reconnu à son contenu, ingéré dans la minute et
rangé dans `inbox/` (`--no-watch` pour l'éviter). Le tableau de bord rappelle quand un
relevé date de plus de deux semaines. Détail : `docs/releves.md`.

Pour sortir les données — déclaration d'impôts, tableur, quelqu'un d'autre — la page
Transactions exporte la fenêtre courante, filtres compris, en CSV ou en xlsx.

Sans Windows :

```bash
uv sync --extra web                # Python, .venv et dépendances (outils de test compris)
uv run python -m pms               # ingestion + contrôle d'intégrité
uv run python -m pms.web           # app web
```

**Sans git ?** Téléchargez le ZIP depuis GitHub, décompressez, lancez `run.bat` : il
propose d'installer git (par winget, l'outil d'installation de Windows), puis fait de la
copie une copie suivie, à la dernière version. Un refus est retenu (`data/no-git`) et
l'app marche quand même, avec des mises à jour à la main.

**Mettre à jour** : quand la branche a avancé sur GitHub, l'app affiche « Mise à jour
disponible » avec la liste des changements, et le bouton fait le `git pull` puis redémarre.
Si les dépendances ont changé, il faut ensuite relancer `run.bat`.

### Sans git : depuis le ZIP

Sur la page GitHub du dépôt : **Code › Download ZIP**. Avant de dézipper, clic droit sur le
ZIP › Propriétés › **Débloquer** (sinon Windows peut bloquer `run.bat`). Double-cliquez
`run.bat` : il propose d'installer git, et la copie devient une copie suivie — le bouton
« Mettre à jour » de l'app marche alors. Sans git, l'app marche, sans mise à jour d'un clic.

Le PDF « Account transactions » d'UBS (e-banking **en anglais**) se dépose tel quel : il est
reconnu à son contenu. Un export UBS s'arrête à 500 mouvements : exporter par tranches.

### Publier pour les autres

Le dépôt de travail peut rester privé : `python tools/publish.py` publie l'état commité dans
le dépôt public, en un commit sans l'historique privé, et refuse si le nom, l'IBAN ou le
numéro de client du titulaire (lus dans le ledger local) apparaissent dans un fichier suivi.
Une copie venue du ZIP public suit ensuite le dépôt public (`run.bat`, `PMS_REPO`).

## Commandes

| Commande | Effet |
|---|---|
| `run.bat` | ingestion + app web |
| `run.bat --check` | contrôle d'intégrité seul, n'écrit rien |
| `run.bat --status` | ce que contient le ledger et d'où ça vient |
| `run.bat --test` | suite de tests (tourne sans relevé : les tests de l'app utilisent un relevé fictif) |
| `run.bat --reparse` | relit aussi les PDF déjà importés — par défaut, un PDF connu n'est pas relu |
| `--export sortie.xlsx` | les transactions classées, en CSV ou en xlsx |
| `--from 2025-01-01 --to 2025-12-31` | limite la fenêtre exportée |
| `--no-ledger` | lecture directe d'un PDF, sans historique |
| `--backup [DOSSIER]` | zippe et chiffre `data/` et `inbox/` (défaut : OneDrive/PMS-sauvegardes), seulement si quelque chose a changé ; `run.bat` le fait à chaque lancement |
| `--restore ARCHIVE [--into DOSSIER]` | déchiffre une sauvegarde et redépose `data/` et `inbox/`, sans rien écraser |
| `--benchmarks` | recapture les repères publics (MSCI World, S&P 500, SMI, or…), dividendes réinvestis |
| `--crypto` | revalorise le relevé crypto Revolut aux cours du jour |
| `--ibkr` | met à jour Interactive Brokers depuis son service Flex (jeton dans `data/ibkr_flex.json`, voir `docs/epargne.md`) |
| `--refresh [--daily]` | IBKR, repères, indices du 3a et crypto d'un coup ; `run.bat` le lance une fois par jour |

## Naviguer dans le temps (app web)

L'app est construite autour d'une seule idée : une fenêtre de dates plus une
granularité déterminent entièrement ce qui est affiché.

- **Préréglages** — 30 jours, 3 mois, 6 mois, 12 mois, l'année en cours, l'année
  précédente, tout. Ils sont calés sur le dernier jour du relevé, pas sur aujourd'hui :
  un relevé est toujours un peu en retard, et compter depuis aujourd'hui donnerait
  des fenêtres vides.
- **Plage libre** — deux champs date, bornés à ce que contient le ledger.
- **Granularité** — année, mois, semaine, jour, ou *auto* (choisie pour garder l'axe
  lisible, environ 10 à 60 colonnes).
- **Zoom** — cliquez une colonne pour y entrer. Année → mois → jour → le détail de la
  journée, mouvement par mouvement, avec le solde après chaque opération.
- **Fil d'ariane** — reconstruit depuis la fenêtre affichée, pas depuis le chemin
  parcouru. Il nomme l'unité calendaire quand la fenêtre en est exactement une.
- **Comparaison** — chaque indicateur est comparé à la fenêtre de même durée qui
  précède immédiatement.

Chaque niveau de zoom est une URL : partageable, marquable, et le bouton retour du
navigateur défait le zoom. `Ctrl K` ouvre une palette qui va à une page, une période ou
une transaction.

L'app est une app React servie par Flask, qui calcule tout et lui envoie du JSON. Le
build est versionné : `run.bat` n'a pas besoin de Node. Pour modifier l'interface,
voir `frontend/README.md`.

## Réimporter un nouveau relevé

Swissquote ne sert qu'une fenêtre glissante de 24 mois, et l'export suivant peut contenir
tout l'historique, seulement le mois écoulé, ou un mélange. Les trois cas donnent le même
résultat : chaque mouvement porte un identifiant unique `(référence, devise)`, et
l'ingestion est une union sur cet identifiant.

- réimporter le même PDF n'ajoute rien ;
- un export chevauchant n'apporte que ses lignes réellement nouvelles ;
- un export incrémental apporte tout son contenu ;
- l'ordre des imports n'a aucune importance.

Le ledger (`data/ledger.json`) conserve donc l'historique **au-delà** de la fenêtre de
24 mois de la banque — c'est sa raison d'être. Déposez simplement chaque nouvel export
dans `inbox/` et relancez.

Deux contrôles tournent à chaque import. Une ligne déjà connue qui revient avec un montant
différent est signalée, pas écrasée silencieusement. Et comme chaque ligne porte le solde
courant imprimé par la banque, une période manquante casse la chaîne et est rapportée
avec son montant exact — le ledger sait dire qu'il est incomplet.

## Ce qui est affiché

Tout est recalculé pour la fenêtre choisie.

- **Indicateurs** — dépensé, encaissé, net, par jour, solde — comparés à la période
  précédente de même durée.
- **Évolution** — colonnes empilées par catégorie ou par besoin/envie/épargne (au
  choix), cliquables pour zoomer.
- **D'où vient l'argent** — une bande dans le temps, une couleur par payeur : qui vous
  payait, et quand ça a changé.
- **Solde du compte** — la courbe, avec crosshair.
- **Faits marquants** — dix chiffres saillants avec leur explication.
- **Besoins / envies / épargne** — parts calculées sur les revenus, repère 50/30/20.
- **Catégories** et **principaux bénéficiaires**.
- **Socle contraint** — ce qu'un mois coûte avant tout arbitrage, et la liste des
  engagements récurrents détectés.
- **Engagements sans passage récent** — un prélèvement régulier qui n'est pas revenu.
- **Calendrier** — une case par jour, cliquable.
- **Cumuls annuels superposés**, **profil par jour de semaine**, **saisonnalité**,
  **dépenses par pays**.
- **Coûts custodian** — le détail de chaque conversion et de la marge prélevée.
- **Épargne** (si les snapshots existent) — compte courant, Interactive Brokers, 3a,
  crypto : valeur, apports, rendement TWR ou MWR, sur la période ou par an, effet du
  timing des versements, contribution de chaque poche, frais, risque, comparaison à des
  repères dividendes réinvestis ; mois de réserve du compte courant, plafond 3a de
  l'année, allocation cible et ce qu'il faut déplacer pour l'atteindre, et la fortune
  au 31.12 pour la déclaration d'impôts (exportable en xlsx).
- **Transactions** — filtrables et triables, jusqu'au détail d'une journée.

Dans l'app, un panneau qui ne peut rien dire sur la fenêtre choisie est simplement
absent : pas de saisonnalité sur trois semaines. Tous les graphiques ont une infobulle,
les courbes ont un crosshair, et chaque graphique a son équivalent tabulaire.

## Fiabilité

Le parser travaille sur les coordonnées des mots, pas sur du texte mis à plat, et se
valide lui-même : les soldes courants sont rapprochés ligne à ligne avec le relevé, et
`solde d'ouverture + net == solde de clôture` au centime près. `run.bat --check` rejoue
ce contrôle sans rien écrire.

La catégorisation est déduite du nom du bénéficiaire par règles (`src/pms/categories.py`).
Elle couvre 99.99 % du montant dépensé sur ce relevé ; ce qui reste est affiché comme
« Non catégorisé » plutôt que rangé au hasard. Ajouter un marchand est une ligne à modifier.

## Brancher une autre banque

**Le plus simple : le faire avec Claude Code.** Ouvrez le dépôt dans
[Claude Code](https://claude.com/claude-code), déposez votre relevé dans `inbox/` et
demandez-lui d'adapter le code à votre banque, par exemple :

> Voici le relevé de ma banque dans `inbox/`. Écris le parser pour ce format, branche-le
> dans l'ingestion, et vérifie que `reconcile()` ne signale aucune rupture.

Le fichier `CLAUDE.md` lui donne le contrat ci-dessous et les pièges déjà rencontrés ;
il lira votre relevé, écrira le parser et le validera sur vos soldes. Le relevé reste sur
votre machine (`inbox/` est exclu de git) — ne le committez pas, et ne recopiez pas ses
lignes dans les tests.

Le détail, pour le faire à la main ou relire ce qui a été fait.
Tout ce qui suit le parser travaille sur trois objets de `src/pms/models.py` :
`Statement`, `AccountSummary` et `Transaction`. Brancher une banque, c'est écrire une
fonction `parse(path) -> Statement` pour son export (PDF, CSV, peu importe) — sur le
modèle de `parser.parse_statement` (PDF) ou de `revolut.parse_statement` (CSV) — et
la déclarer dans `banks.py`.

### Ce que le parser doit remplir

| Champ | Exigence | Pourquoi |
|---|---|---|
| `Transaction.reference` | unique **par devise** et stable d'un export à l'autre | `(référence, devise)` est l'identité du mouvement : dédoublonnage, épingles, ré-import. Si la banque n'en imprime pas, en dériver une (date + montant + libellé + rang du jour), jamais un compteur global qui changerait selon le début de l'export. |
| `date`, `currency`, `amount` | montant **signé** : négatif = sortie | toute l'arithmétique en dépend |
| `balance` | le solde après le mouvement, s'il est imprimé ; sinon `None` | c'est ce qui permet à `reconcile()` de prouver qu'aucune ligne n'est perdue |
| `seq` | rang de la ligne parmi celles de la même devise **le même jour** | rejoue l'ordre de la banque, donc la chaîne des soldes |
| `kind` | le type d'opération tel qu'imprimé (« Paiement par carte »…) | les règles et plusieurs vues s'y fient (voir plus bas) |
| `merchant`, `location`, `detail` | contrepartie, lieu (`…, Pays` pour une carte), toutes les lignes brutes | catégorisation, géographie, recherche |
| `Statement.accounts` | un `AccountSummary` par devise, soldes d'ouverture et de clôture | sans lui, `reconcile()` ne peut pas vérifier la clôture |
| `Transaction.account` | `""` pour le compte principal, un nom court (`"revolut"`) pour tout autre | chaque compte garde sa propre chaîne de soldes ; le cash affiché est leur somme |
| `Statement.reference_currency` | la devise de référence | aujourd'hui `CHF` est supposé partout (voir limites) |

Le critère d'acceptation est le même que pour Swissquote : sur un vrai relevé,
`reconcile(statement)` renvoie une liste vide, et `solde d'ouverture + net == solde de
clôture` au centime pour chaque devise.

### Le vocabulaire propre à la banque

Le libellé des opérations varie d'une banque à l'autre. Ce qui est aujourd'hui calé sur
celui de Swissquote, et qu'il faut soit faire correspondre dans le parser (recommandé :
normaliser `kind` vers ces libellés), soit étendre :

| Où | Quoi |
|---|---|
| `analysis.FX_KINDS`, `parser._enrich_forex` | les deux jambes d'une conversion de devises (même référence, `fx_counter_amount` = CHF débités) |
| `categories.PEER_KINDS`, `INCOMING_KINDS` | paiement entre particuliers (Twint), crédit entrant |
| `categories.py`, `models.Transaction.label` | `"Versement pour X"` = virement sortant vers X |
| `review.CARD_KIND` | paiement par carte |
| `analysis.country_of` | le pays est le dernier segment de `location` après une virgule |
| `categories.py`, règle « Frais bancaires » | les libellés de change et d'intérêts |
| `categories.INTERNAL` | un virement entre vos propres comptes (une recharge Revolut) : ni dépense ni revenu, des deux côtés |

### Le brancher

Une ligne dans `banks.SOURCES` : où ses exports sont déposés dans `inbox/`, et son
parser. La CLI et le bouton ⟳ de l'app lisent ce registre ; un fichier déposé ailleurs
est refusé plutôt que lu par le mauvais parser.

Si la banque est un **compte secondaire** (une carte de voyage, un néo-banque), ses
lignes portent un `account` et vivent à côté du compte principal. Ses lignes antérieures
au début du compte principal restent dans le ledger mais hors de l'analyse : une année
où seul le petit compte est connu se lirait comme une année sans dépenses. Importer un
relevé plus ancien du compte principal les fait entrer d'elles-mêmes.

Ajouter ensuite ses tests sur un export inventé de la même forme (`tests/test_revolut.py`
en est le modèle), jamais recopié d'un vrai relevé.

### Limites connues

- **Le franc est la devise de référence.** `annotate_chf`, les montants affichés et
  l'épargne raisonnent en CHF ; une banque en EUR demanderait de généraliser ce point.
- **Une conversion sans montant débité imprimé** (seulement un taux) donne un montant
  converti estimé, pas exact, et pas de coût de change mesurable.
- **Sans solde courant imprimé**, une ligne perdue ne se voit plus que sur le total de
  clôture — plus de localisation de la rupture.
- Les panneaux Épargne (Interactive Brokers, 3a finpension) sont optionnels : sans
  `data/ibkr.json` ni `data/finpension.json`, ils sont absents.

## Confidentialité

`inbox/`, `data/` et `output/` sont exclus de git : les relevés, le ledger, les
corrections et les exports restent sur votre machine. Un export CSV ou xlsx contient
l'intégralité de vos transactions — ne le publiez pas.

Ce que `data/` contient ne se reconstruit pas entièrement : le ledger se refait depuis
les relevés, vos corrections, règles et budgets non. `run.bat` en dépose donc une copie
zippée **et chiffrée** (avec `inbox/`) dans OneDrive à chaque lancement où quelque chose
a changé, en gardant les dix dernières (`--backup DOSSIER --keep N` pour ailleurs ; un
dossier dans le dépôt est refusé). La clé est créée au premier passage dans
`data/backup.key` et n'entre jamais dans une copie : **gardez-en une copie dans votre
gestionnaire de mots de passe**, sans elle les sauvegardes ne se relisent pas.
Restaurer : `python -m pms --restore ARCHIVE` (la clé est demandée si `data/` n'existe
plus). Détail : `docs/sauvegarde.md`.

## L'assistant (facultatif)

Un modèle de langage peut proposer une catégorie aux commerçants inconnus, résumer la
revue du mois, expliquer pourquoi un mois a coûté plus, répondre à une question en
français depuis `Ctrl K` et traduire une phrase en scénario de prévision. Il est éteint
par défaut. Pour l'allumer : poser la clé du fournisseur seule sur une ligne dans
`data/ai.anthropic.key` (Claude) ou `data/ai.deepseek.key` (DeepSeek) — rien pour
Ollama, qui tourne sur le PC — puis choisir le fournisseur et le modèle dans la page
**Assistant** de l'app, et « Tester ». Il ne calcule aucun chiffre : l'app lui donne les
siens et écarte toute phrase qui en cite un autre. Les noms de personnes partent masqués
et chaque envoi est noté dans `data/ai_log.jsonl`. Détail : `docs/assistant.md`.

## Sur le téléphone

L'app reste sur `127.0.0.1` ; [Tailscale](https://tailscale.com) la porte jusqu'à vos
appareils, et à eux seuls. Une fois : installer Tailscale sur le PC et le téléphone avec
le même compte, puis, sur le PC, `tailscale serve --bg 5000`. Au lancement, l'app affiche
l'adresse à ouvrir sur le téléphone (`https://<pc>.<tailnet>.ts.net/`) et empêche Windows
de se mettre en veille tant qu'elle tourne. Jamais `tailscale funnel`, qui la mettrait
sur internet sans mot de passe. Sur le téléphone, l'app a des onglets en bas, des
graphiques à la largeur de l'écran qu'on lit au doigt, et s'installe sur l'écran
d'accueil. Un relevé s'envoie depuis le téléphone par « Plus › Importer » (`/importer`).
Détail et raisons : `docs/acces-distant.md`.

Les règles de catégorisation qui nommeraient un employeur, une régie, un praticien ou
une personne vont dans `data/local_rules.json`, également exclu. Copiez
`data/local_rules.example.json` pour démarrer. Le dépôt lui-même ne contient que du
commerce public (Coop, SBB, Uber, Swisscom) et aucune valeur identifiante.
