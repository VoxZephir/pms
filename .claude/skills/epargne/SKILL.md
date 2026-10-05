---
name: epargne
description: Mettre à jour les snapshots d'épargne hors relevé — IBKR (data/ibkr.json) et le 3a finpension (data/finpension.json) — avec le connecteur IBKR. À utiliser quand l'utilisateur demande si l'épargne est à jour, de recapturer IBKR ou le 3a, ou quand le panneau Épargne affiche « Snapshot en retard ».
---

# Recapturer l'épargne

Les deux snapshots sont figés à la capture ; l'app ne lit jamais en direct
(`docs/epargne.md`). Une capture **ajoute** les points manquants, elle ne
réécrit jamais l'historique : c'est `python -m pms --capture` qui le garantit,
ne pas éditer les JSON à la main.

## 1. Où s'arrêtent les séries

```bash
.venv/Scripts/python -m pms --status
```

La section « épargne » donne la dernière date de `nav`, `nav_daily` et de
chaque série de cours du 3a. On ne récupère que ce qui vient après.

## 2. Le connecteur

Il doit être connecté dans la session (outils `get_account_summary`, etc.).
S'il manque ou demande une authentification, le dire à l'utilisateur
(`/mcp`) et s'arrêter — ne jamais lui demander de code ou de jeton.

Appels, tous en lecture seule — ne jamais appeler un outil qui crée un
ordre, une alerte ou une watchlist :

| Donnée | Outil | Paramètres |
|---|---|---|
| valeur, cash, marge | `get_account_summary` | — |
| cash par devise, taux USD→CHF | `get_account_balances` | — |
| position | `get_account_positions` | — |
| NAV quotidienne, TWR | `get_pa_performance_all_periods` | — (période `YTD` ou `1Y` : `dates` / `nav` parallèles) |
| prix de la position | `get_price_history` | contract_id de la position, `STK`, `ONE_DAY`, `THREE_MONTHS` |
| SMI | `get_price_history` | 1328305, `IND`, exchange `EUREX` |
| URTH | `get_price_history` | 100223106, `STK` |
| EEM | `get_price_history` | 6604766, `STK` |
| USD.CHF | `get_price_history` | 12087820, `CASH`, exchange `IDEALPRO` |

Pièges connus :

- **USD.CHF est horodaté la veille** : une barre `…T21:15:00Z` appartient à la
  séance du lendemain (dimanche 21:15 = lundi). Décaler d'un jour avant de
  multiplier.
- `URTHxCHF` = clôture URTH × USD.CHF **du même jour de séance**. Un jour sans
  cours US (Labor Day…) n'a pas de point — c'est normal, `_level_at` prend le
  précédent.
- Le SMI cote des jours où la bourse US est fermée, et inversement.
- La valeur de la position en CHF = `stock_market_value` de la ligne `BASE`
  de `get_account_balances` ; le `market_value` de `get_account_positions`
  suit un prix plus récent et ne se réconcilie pas avec la valeur du compte.
- `performance.one_year_pct` = dernier `cps` de la période `1Y` × 100 ;
  `ytd_pct` = dernier `cps` de `YTD` × 100.
- **Les `nav` se prennent dans la série de performance** (`1Y`, `dates` / `nav`
  parallèles) : c'est la NAV exacte du courtier, quotidienne. Depuis le
  02.10.2026 le snapshot en est fait à partir du 01.10.2025 ; l'ancienne
  reconstruction (prix × ancres mensuelles) s'en écartait de 5 %.

### Les versements

Une NAV qui saute d'un versement n'est pas une performance. Pour chaque jour
capturé, le versement implicite vaut
`nav_t − nav_(t−1) × (1 + cps_t) / (1 + cps_(t−1))` (même période `cps`).
Au-delà de ~50 CHF :

- s'il y a, à ±3 jours, un virement Swissquote vers Interactive Brokers dans
  le ledger, **ne rien faire** : `ibkr.flows()` le lit dans le relevé ;
- sinon, c'est un versement venu d'ailleurs : l'ajouter à la capture,
  `"flows": [["AAAA-MM-JJ", montant_CHF]]` (+ entrée, − retrait), et le dire
  à l'utilisateur.

`get_account_trades` (`DAYS_30`) confirme : conversion CHF→USD puis achat
« IBRECINV » (investissement récurrent) après un versement.

### Les frais

`get_account_trades` sur la période écoulée depuis la dernière capture
(`DAYS_30`, `DAYS_90`…). Pour chaque opération, une entrée `costs` en CHF
(taux USD.CHF de la séance) :

- `commission` non nulle → `{"kind": "commission d'achat" | "commission de
  change", "label": "<ce qui a été fait> : <montant> <devise>", ...}` ;
- conversions FXCONV passées par paires au même instant (achat et vente du
  même montant à deux prix) → l'écart, `taille × (prix d'achat − prix de
  vente)`, `kind: "écart de change automatique"`.

Une entrée est appariée entière (date, libellé, montant) : relancer ne
compte rien deux fois. `costs_known_from` ne se pose qu'une fois (la plus
ancienne période que le connecteur a rendue).

### L'historique des transactions (export CSV)

Si l'utilisateur a déposé un nouvel export « Transaction History » dans
`inbox/ibkr/` (IBKR → Rapports → Relevés de transactions, depuis l'ouverture) :

```bash
.venv/Scripts/python -m pms --ibkr-journal
```

Il remplace les versements et les frais par ceux de l'export (complets
depuis 2023) — dans ce cas, ne pas déclarer de `flows` à la main. La valeur
d'avant la NAV quotidienne du courtier est reconstruite à partir de ses
positions et de cours **hebdomadaires** (`prices` dans la capture :
`get_price_history` du titre et de USD.CHF, `ONE_WEEK`, `FIVE_YEARS` ; les
barres sont datées du lundi). Ne recopier un tableau de cours qu'en entier,
dates et clôtures ensemble : un extrait à la main se décale d'une semaine
sans qu'on le voie. Vérifier ensuite que la valeur reconstruite rejoint la
NAV du courtier au raccord (à 0.1 % près).

## 3. Écrire la capture et la fusionner

Écrire un JSON dans le scratchpad (jamais dans le dépôt), avec seulement les
points postérieurs aux dates de l'étape 1 :

```json
{
  "ibkr": {
    "captured_at": "AAAA-MM-JJTHH:MM:SS",
    "fx_chf_per_usd": 0.8206,
    "account": {"net_liquidation": 0, "equity_with_loan": 0, "buying_power": 0,
                "total_cash": 0, "available_funds": 0, "initial_margin": 0},
    "cash": [{"currency": "USD", "amount": 0}, {"currency": "CHF", "amount": 0}],
    "performance": {"ytd_pct": 0, "one_year_pct": 0},
    "positions": [{"name": "…", "quantity": 0, "market_price": 0,
                   "market_value": 0, "market_value_chf": 0,
                   "unrealized_pnl": 0, "unrealized_pnl_chf": 0,
                   "unrealized_pnl_pct": 0}],
    "nav": [["AAAA-MM-JJ", 0]],
    "nav_daily": [["AAAA-MM-JJ", 0]],
    "flows": [],
    "costs": [{"date": "AAAA-MM-JJ", "kind": "commission d'achat",
               "label": "…", "amount_chf": 0}]
  },
  "proxy_series": {"SMI": [["AAAA-MM-JJ", 0]], "URTHxCHF": [["AAAA-MM-JJ", 0]],
                   "EEM": [["AAAA-MM-JJ", 0]]}
}
```

`nav_daily` porte le **prix** de la position (pas la NAV) ; `ibkr.load` le
met à l'échelle sur `nav`. Une position est appariée par `name` : ses champs
déclarés à la main (`asset_split`, `geography`, `exposure`) sont gardés.

```bash
.venv/Scripts/python -m pms --capture <scratchpad>/capture.json
```

Relancer la même capture ne change rien (seuls les points plus récents
entrent).

## 4. La valeur réelle du 3a

Si l'utilisateur donne la valeur lue dans l'app finpension :

```bash
.venv/Scripts/python -m pms --3a-value 10000 --on AAAA-MM-JJ
```

La lecture précédente passe dans les observations (`yearly`) — sans ça la
courbe se ré-ancre sur une lecture plus ancienne et saute d'un jour à l'autre.
Sans valeur lue, les cours prolongés à l'étape 3 suffisent : le 3a est estimé
depuis la dernière lecture.

## 5. Vérifier et rendre compte

- `python -m pms --status` : les séries vont jusqu'à la date attendue.
- Le panneau Épargne n'affiche plus « Snapshot en retard » sur le mois en
  cours (le fichier est relu à chaque requête, pas besoin de redémarrer).
- La performance IBKR du panneau sur le mois écoulé = le `cps` d'IBKR sur la
  même période (à 0.1 point) ; un écart veut dire un versement non déclaré.
- Rendre compte : valeur IBKR avant → après **en séparant versement et
  performance**, 3a avant → après (en disant si c'est une estimation ou une
  lecture), et rien à committer (`data/` est gitignoré).
