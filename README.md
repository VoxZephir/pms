# Analyse de relevés bancaires

Lit un relevé de transactions bancaire, catégorise les dépenses, chiffre ce que la
banque a prélevé, et le rend explorable dans une app web locale.

Le parser livré lit le relevé PDF de **Swissquote**. Toute autre banque se branche en
écrivant un seul module — voir [Brancher une autre banque](#brancher-une-autre-banque) :
le ledger, la catégorisation, l'analyse et l'app ne connaissent que le modèle commun.

## Démarrage

Déposez votre relevé dans `inbox/`, puis :

```bash
run.bat
```

Le script crée l'environnement virtuel et installe les dépendances au premier lancement,
ingère les PDF de `inbox/`, puis démarre l'app sur http://127.0.0.1:5000.

Pour sortir les données — déclaration d'impôts, tableur, quelqu'un d'autre — la page
Transactions exporte la fenêtre courante, filtres compris, en CSV ou en xlsx.

Sans Windows :

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[web,dev]"
.venv/Scripts/python -m pms        # ingestion + contrôle d'intégrité
.venv/Scripts/python -m pms.web    # app web
```

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
navigateur défait le zoom. Tout fonctionne sans JavaScript ; celui-ci ne sert qu'à
éviter le rechargement complet.

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
modèle de `parser.parse_statement` — et la passer à l'ingestion.

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

### Le brancher

L'ingestion prend la fonction de parsing en paramètre (`ledger.ingest(paths, ledger_path,
parse)`) ; elle est aujourd'hui passée à deux endroits, `cli.py` et
`web/views/system.py`, qui lisent `inbox/*.pdf`. Il n'y a pas de détection automatique
de la banque : pour une seule banque, remplacer `parse_statement` à ces deux endroits
(et le motif de fichier si l'export n'est pas un PDF) suffit.

Ajouter ensuite un test de parser à côté de `tests/test_parser.py` (sauté sans relevé
réel), et, si la banque a une forme de données que le relevé fictif n'a pas, l'ajouter
à `tests/synthetic.py` — inventée, jamais recopiée d'un vrai relevé.

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

Les règles de catégorisation qui nommeraient un employeur, une régie, un praticien ou
une personne vont dans `data/local_rules.json`, également exclu. Copiez
`data/local_rules.example.json` pour démarrer. Le dépôt lui-même ne contient que du
commerce public (Coop, SBB, Uber, Swisscom) et aucune valeur identifiante.
