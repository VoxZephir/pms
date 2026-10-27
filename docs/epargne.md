# Épargne hors relevé (Interactive Brokers, 3a)

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

**Le compte courtage ne fait pas partie du relevé Swissquote** — c'est exactement
l'épargne qui manque au bucket `Save`. IBKR n'expose que des *états* (équité, cash,
positions, courbe NAV), pas un journal de transactions : le connecteur MCP est rattaché
à une session Claude Code, pas à l'app. D'où `data/ibkr.json` (gitignoré,
`ibkr.example.json` versionné) : un **snapshot capturé via le connecteur, figé à la
capture comme un relevé**. Le panneau `p-ibkr` le lit à chaque requête. Une capture se
refait en session Claude Code avec le connecteur connecté ; l'app ne fait jamais de
lecture en direct.

**La page se lit de haut en bas** (refonte du 02.10.2026, reprise le 19.10), chaque partie
répondant à une question, toutes sensibles à la fenêtre :

1. **Vue** (`?focus=total|swissquote|ibkr|finpension|crypto`) — le sélecteur de comptes de
   la barre du haut, ou une carte de poche.
2. **Le bandeau** — ce que vaut la poche à la fin de la période ; de combien elle a bougé,
   **séparé entre l'argent mis (« mis de côté », « versés ») et le rendement** ; la
   performance, TWR ou MWR, sur la période ou par an ; les repères.
3. **Les poches en cartes** — valeur, part, la courbe de la fenêtre en miniature
   (`reads.sparks`, 48 points), le rendement en francs et en %, ce qui a été versé. Une
   carte ouvre la poche (`?focus=`) ; la carte choisie est cerclée et ramène au total.
   Elles remplacent le tableau « Par poche » en tête : il est replié plus bas (« Par
   poche, en détail ») pour la contribution, le timing et les frais.
4. **Évolution** — Montants · Base 100 ; en montants, « Lignes » ou **« Empilé »** (une
   bande par poche, le haut est le total ; choix local, pas dans l'URL — le même argent
   vu autrement, comme le découpage de Prévisions). Pas d'empilement si une part passe
   sous zéro. « Zoom » (l'axe ajusté aux valeurs) est retiré le 18.10 : la courbe
   Swissquote frôle zéro, l'axe ajusté était donc celui des montants.
5. **D'où vient la variation** — une cascade : l'épargne au début, ce qui a été mis de
   côté (le flux net du total : entré moins dépensé), le rendement de chaque poche, la fin
   (`savings_reads.bridge`). Chaque poche est lue sur la même fenêtre, donc les marches
   somment exactement au bandeau ; un virement entre deux poches sort de l'une et entre
   dans l'autre, ce n'est jamais une marche. Le dessin est partagé avec Prévisions
   (`components/Bridge.tsx`). À côté, la **composition**.
6. **Versements et valeur** — plus bas.
7. **Mois par mois** — le TWR de chaque mois, une année par ligne, colorié du rouge au
   vert (`savings_reads.monthly_returns`), lu sur l'indice quotidien de la table de risque :
   les mois se chaînent en l'année, les années au TWR de la fenêtre (testé). Un mois coupé
   par la fenêtre est en italique et n'entre ni dans « meilleur » ni dans « pire ». Une
   poche à la fois, IBKR par défaut : le total est dilué par le compte courant.
8. **Baisses depuis le plus haut** — l'écart au plus haut, jour par jour, sur le même indice
   (un retrait n'est pas une baisse) : la pire, du plus haut au creux, le temps de remontée
   (ou « pas encore »), l'écart d'aujourd'hui (`savings_reads.drawdown`, au plus 420 points,
   le creux de chaque tranche gardé).
9. **Réserve et plafond 3a**, puis les replis : le détail par poche, l'allocation cible, la
   crypto, les frais, la déclaration d'impôts, **risque et statistiques**.
10. **Sources** — en français, sans chemins de fichiers.

**Un seul livre derrière tout : `SavingsBook`** (`views/savings.py`). Valeur de chaque
poche et chaque franc entré ou sorti, jour par jour ; le bandeau, le tableau, la base 100
et la table de risque le lisent tous, pour qu'aucune partie ne contredise une autre sur ce
qu'est un versement. Ses règles : un virement Swissquote → IBKR sort d'une poche, entre
dans l'autre, ne change rien au total ; IBKR ne vaut rien avant son premier point et sa
valeur d'ouverture est un versement ; un dépôt 3a (`deposit_entries`, daté depuis le
journal) est un versement. `balance_at`, `nav_at` et `_level_at` sont bissectés et les
flux cumulés, sinon le calcul jour par jour sur deux ans coûtait des secondes (≈150 ms
la page « Tout »). Les montants IBKR sont en CHF : le snapshot porte les valeurs en devise
*et* leur équivalent CHF au taux de capture (`market_value_chf`, etc.).

**Un versement n'est pas une performance.** Tant que le cash du compte n'avait jamais
bougé, le rapport de deux NAV *était* le rendement, et MWR = TWR. Puis un virement est
parti de Swissquote vers IBKR (converti en USD quelques jours plus tard, puis investi par
l'investissement récurrent). Le rapport de deux NAV a lu le mois et les douze mois
gonflés de plusieurs dizaines de points par rapport aux chiffres d'IBKR ; la performance
totale, elle, comptait le débit Swissquote comme un retrait alors que l'argent restait
dans l'épargne. Désormais :

- **les versements viennent du ledger** (`ibkr.flows`) : un virement Swissquote vers
  Interactive Brokers est un versement vu de l'autre côté — rien à capturer, chaque relevé
  apporte les siens. Un versement venu d'ailleurs se déclare dans le snapshot (`flows`) ;
  `/epargne` le détecte comme un saut de NAV que le `cps` d'IBKR n'explique pas ;
- **le TWR est chaîné point à point**, le versement rejoignant la base au début de son
  intervalle, `v1 / (v0 + flux)` — la convention d'IBKR : le jour du versement, elle
  redonne le chiffre du courtier, dont `(v1 − flux) / v0` s'écartait ;
- **la performance totale** rajoute le versement côté IBKR au flux du mois : il annule le
  débit Swissquote, puisque l'argent n'a pas quitté l'épargne ;
- **la table de statistiques** retire à chaque colonne la part du versement qu'elle porte
  (`_ibkr_share` : IBKR, USD, le fonds en entier ; actions / trend-following à 50 % ; la
  géographie selon la position) ; la MWRR d'IBKR passe à « — » sur une période avec
  versement, faute de XIRR.

Le financement initial du compte peut précéder le ledger : il reste alors inconnu, sauf
par l'export « Transaction History » (plus bas).

**TWR ou MWR, au choix (`?perf=twr|mwr`).** Le TWR dit ce qu'ont fait les placements,
quels que soient les versements ; le MWR ce qu'a fait l'argent du titulaire, chaque
versement pondéré par sa durée (`analysis.xirr`, `money_weighted`, par bissection : la
dérivée s'annule sur les flux d'un compte courant). Les deux sont donnés *sur la période*
dans la carte, annualisés dans la table. Le MWR total compte salaires et dépenses comme
versements et retraits de l'épargne ; le côté IBKR d'un virement annule son côté
Swissquote. Un mois où un versement arrive juste avant un repli a un MWR un peu sous son
TWR : c'est l'argent versé qui a subi le repli, pas les placements.

**Base 100 (`?scale=index`).** Chaque ligne repart de 100 à son premier point : on
compare des performances, plus des tailles — un petit courtage et un compte courant
plusieurs fois plus gros sur un même axe ne disaient pas lequel avait fait mieux. En TWR, l'indice est
chaîné versements retirés (`_indexed_rows`, le même `_key_flow` que la table) ; en MWR,
chaque point vaut 100 × (1 + MWR depuis le premier point), versements à leur date
(`_mwr_rows`) — un MWR ne se chaîne pas. En CHF le sélecteur ne change rien au graphique
(une valeur est une valeur) et la légende le dit. **La valeur d'ouverture d'IBKR compte
comme un versement** pour les lignes qui l'agrègent : financée hors du ledger, elle
faisait finir l'épargne totale bien trop haut en base 100 sur tout l'historique.

**Les frais, par poche et par période** (« Frais sur la période ») :

- **Swissquote** — la marge de change et les intérêts négatifs, le chiffre de la section
  custodian ;
- **IBKR** — capturés depuis ses opérations (`costs` dans le snapshot, via `/epargne`) :
  commissions, et l'écart achat/vente des conversions automatiques qu'il passe par paires
  (FXCONV : des USD achetés puis revendus le même jour à un cours un peu plus bas — un
  écart de l'ordre de 0.1 %). L'historique du connecteur ne remonte qu'à un an, et son
  premier trimestre peut être vide : un achat plus ancien n'est pas connu, et la ligne le
  dit (`costs_known_from`) ;
- **3a** — les frais administratifs forfaitaires trimestriels du journal, désormais datés
  (`fee_entries`), pour qu'une fenêtre dise ce qu'elle a coûté.

Les frais internes des fonds (TER) sont dans les prix des trois poches et sur aucun relevé :
ils ne sont pas estimés, la légende le dit. En chemin : `--finpension` effaçait la
géographie et le nom court déclarés à la main pour chaque fonds — la répartition
géographique avec eux. La régénération les garde désormais.

**L'historique complet vient de l'export « Transaction History » d'IBKR**
(`inbox/ibkr/*TRANSACTIONS*.csv`, `python -m pms --ibkr-journal`, `ibkr_history.py`).
Le connecteur ne voit qu'un an : l'app a cru le compte ouvert un an avant la capture.
Il était bien plus ancien, et avait traversé le krach des tarifs d'avril 2025 — sa pire
baisse sur tout l'historique est **bien plus profonde** que celle de la seule année
visible. L'export donne :

- **les versements et retraits depuis l'ouverture**. Quand l'export est là, il remplace
  la lecture du ledger — lire les deux compterait chaque virement deux fois ;
- **les frais depuis l'ouverture** : commissions, écart des conversions automatiques
  passées par paires, retenue US nette par dividende (un dividende peut porter deux
  prélèvements et un remboursement : la retenue est leur somme, pas le premier) ;
- **les positions et la trésorerie jour par jour**, d'où la **valeur reconstruite chaque
  semaine** jusqu'au début de la NAV quotidienne du courtier : parts × clôture du
  vendredi × USD.CHF du vendredi, plus la trésorerie (`ibkr_history.rebuild`, cours
  hebdomadaires capturés dans `prices` via `--capture`). Contrôle : la valeur reconstruite
  au premier jour de la NAV du courtier s'en écarte de quelques centièmes de pour-cent.
  Une semaine qui détient un titre sans cours est sautée, pas devinée : l'app lit à
  partir du moment où le compte ne détient plus que des titres dont les cours sont
  capturés (les positions vendues avant n'en ont pas).

**Un versement va au point de valeur qui le montre** (`ibkr._snap`). Le courtier peut
dater un versement de la veille du jour où Swissquote le débite et où la NAV bouge ; un
retrait apparaît dans le point hebdomadaire du lendemain. Daté la veille de son
point, un flux se lit comme une chute d'un jour suivie d'un bond — un faux −20 % dans la
pire baisse. Chacun va au premier point qui le suit, ou au suivant si c'est là que la
valeur bouge d'à peu près son montant ; un flux antérieur au premier point est déjà dedans.

**Le retour d'argent du courtier n'est pas un revenu.** Le virement d'un retrait nomme
le titulaire comme expéditeur ; seul le BIC (`IBKRUS33…`) dit Interactive Brokers. Il
était classé « Revenus » — un salaire fantôme de plusieurs milliers de CHF. Il est
désormais « Épargne & investissement / Retrait de courtage » (`categories.BROKER_BIC`).

**Des repères : MSCI World (CHF) et SMI.** Les proxies du 3a, capturés chaque jour depuis
le début du 3a, servent aussi d'indices de comparaison (`savings.BENCHMARKS`) ; un indice
capturé dans `ibkr.json` (`benchmarks`, via `--capture`) s'y ajoute — un S&P 500 en CHF,
par exemple. Ils apparaissent dans le bandeau (« sur la même période »), en pointillés
dans la courbe en base 100 (vue par compte seulement : une vue de répartition occupe déjà
toutes les teintes) et comme colonnes de la table de risque, mesurés exactement comme les
poches. C'étaient des **indices de prix** : sans dividendes, ils sous-estimaient un
ETF réel d'environ 1,8 % (monde) à 3 % (SMI) par an. Depuis le 08.10 ils sont lus
dividendes réinvestis (section « Les repères, au choix »).

**La performance IBKR se décompose entre le fonds et le dollar** (`_attribution`) :
`(1 + fonds)(1 + devise)(1 + reste) = 1 + TWR` — le fonds dans sa monnaie (en USD),
le dollar contre le franc, et le reste (dividendes, trésorerie, frais, moment d'un
versement) qui ferme l'écart. Le taux USD.CHF n'est **pas capturé** là où la NAV
quotidienne du courtier existe : il en est **déduit** (NAV = parts × cours × taux +
trésorerie, une seule inconnue) — à quelques cent-millièmes du taux imprimé dans le
relevé IBKR ; avant, la série hebdomadaire de la reconstruction. Une copie à la main de 260
cours de change aurait été la seule autre voie, et elle s'était décalée d'une semaine la
fois où elle a été tentée. Lecture sur le ledger réel : pendant le krach des tarifs du
premier semestre 2025, **la monnaie a coûté plus que le fonds**. Une poche à plusieurs fonds ou
sans cours ne reçoit pas de décomposition plutôt qu'une inventée.

**La NAV IBKR est celle du courtier sur l'année que couvre le connecteur.** La série de
performance (`1Y`) donne la NAV exacte de chaque jour ; capturée le 02.10.2026, elle a
remplacé — exception unique à « une capture n'ajoute que » — la reconstruction d'avant,
qui s'en écartait jusqu'à 5 %. Le prix quotidien
mis à l'échelle (`nav_daily`) ne sert plus qu'à combler les jours sans NAV.

**Un box cliqué (`?focus=`) décompose la poche, pas le portefeuille.** IBKR est du USD
plus son cash CHF, la 3a ses fonds, Swissquote du cash quelle que soit la vue — la barre
remplit à la valeur de la poche, et le spec du graphique (construit par `_split_series`)
nomme ses lignes : un spec explicite gagne toujours sur le filtre de focus, qui ne
s'applique qu'au spec par défaut. `?scale=auto` cale **les deux bouts** de l'axe y sur
les données (`auto_ceiling`, deux chiffres significatifs) ; le mode zéro garde un haut
d'axe rond (`nice_ceiling`).

**La table de risque est quotidienne, depuis le premier jour de la fenêtre**
(`_risk_table`, l'indice TWR jour par jour de `SavingsBook`, annualisé selon
l'échantillonnage : `risk_stats(..., periods_per_year=365.25)`). La version mensuelle
qu'elle remplace commençait à la fin du premier mois — le premier mois manquait — et ne
voyait que 11 points par an. Mesurée contre la NAV quotidienne d'IBKR sur une année, elle
sous-estimait le rendement d'environ un quart, la pire baisse de moitié et la volatilité
d'environ 40 %. Désormais :

- **sous un an, rien n'est extrapolé par défaut** — un bon mois s'affichait à
  plus de +100 %/an. Les jours se comptent inclusivement : du 01.10 au 30.09, c'est un an, pas
  364 jours. La table a deux lectures (`?stats=annual|period`, `stats_mode`) : sans
  paramètre, annualisée à partir d'un an et **sur la période** en dessous. Sur la
  période, rien n'est ramené à un an : volatilité = σ quotidienne × √(nombre de jours),
  taux sans risque = 0,5 %/an composé sur la durée, et Sharpe, Sortino, Calmar, UPI
  divisent le rendement de la fenêtre (`risk_stats(...)["period"]`). Ces ratios ne se
  comparent qu'entre colonnes d'une même fenêtre. Choisir « Annualisé » sous un an
  extrapole, à la demande, et la note le dit (`extrapolated`). Jusqu'au 17.10, la table
  laissait simplement ces lignes vides sous un an — l'utilisateur voulait des chiffres ;
- **une poche plus jeune que la fenêtre est mesurée depuis son premier jour, et l'en-tête
  le dit** (« IBKR (depuis le JJ.MM.AAAA) ») : une poche dont la série commence après un
  krach ne le contient pas dans sa pire baisse, même si le fonds l'a traversé ;
- **le 3a est marqué « estimé »** : entre deux relevés il suit des indices de référence ;
- **la dilution du total est dite** : une large part de compte courant à rendement nul
  aplatit sa volatilité et flatte son Sharpe ;
- chaque ligne porte sa définition en clair ; l'Ulcer index est en %.

Grain jour, semaine ou mois : mêmes chiffres, la table ne dépend pas de la courbe.

**Les deux courbes passent au journalier.** Le snapshot IBKR porte `nav_daily` : le prix
quotidien de la position (pas la NAV), mis à l'échelle sur les NAV mensuelles comme la
reconstruction du 3a — accord exact aux ancres, forme du fond entre elles. Le 3a n'a pas
de NAV quotidienne publiée, donc `proxy_series` est capturé en quotidien (SMI,
URTH×USD.CHF, EEM) — le couple USD.CHF n'imprime pas de barre le vendredi ni certains
fériés, `_level_at` rend les trous inoffensifs. Les anciens points mensuels étaient des
clôtures de fin de mois étiquetées au premier jour de bourse ; le quotidien corrige ce
décalage d'étiquette.

**Le 3a finpension est la troisième pierre.** `inbox/finpension/` reçoit le journal CSV
et les rapports de performance ; `finpension.py` les lit (le journal résume dépôts,
dividendes, frais, et les parts détenues par ISIN) et `data/finpension.json` (gitignoré)
fige le tout. La valeur n'est pas dans le journal — il ne montre que le cash — donc elle
vient du rapport le plus récent, ou d'une **reconstruction** : cash du journal + parts ×
prix de fonds indiciels similaires (SMI, URTH×USD.CHF, EEM — les fonds exacts ne sont pas
cotés chez IBKR), capturée en session avec le connecteur. Le snapshot porte le mapping
`proxies` (ISIN → proxy) qui relie chaque fond à sa série — sans lui, la reconstruction
reste un escalier silencieux. Mettre à jour : déposer les nouveaux documents dans
`inbox/finpension/` puis `python -m pms --finpension` (la régénération garde une
reconstruction plus récente que le rapport, les proxies et leur mapping).

**Recapturer : la skill `/epargne`, et `--capture`.** La mise à jour du 22.09 s'est faite
par scripts écrits à la main, et elle a commis les deux erreurs que `snapshots.py` rend
désormais impossibles :

- **réécrire l'historique** — une capture n'*ajoute* que les points postérieurs à la
  dernière date de chaque série (`append_after`) ; relancer la même capture ne change
  rien, un point qui chevauche l'historique est ignoré, jamais écrasé ;
- **perdre la lecture 3a précédente** — `finpension.observe()` (`--3a-value X --on
  DATE`) la verse dans `yearly` avant d'écrire la nouvelle. Écrasée, elle faisait
  ré-ancrer tout le mois sur la lecture du mois d'avant : la courbe sautait d'un jour à
  l'autre. Une lecture plus ancienne que la courbe n'est qu'une observation, elle ne
  remplace jamais la plus récente.

`--status` imprime où s'arrête chaque série, pour ne demander au connecteur que la
suite ; un nom de série de cours inconnu est refusé (une faute de frappe créait une
série que rien ne lit, et le 3a restait figé pendant que la capture se disait réussie).
La marche à suivre, outils du connecteur et pièges compris (USD.CHF horodaté la veille,
la valeur de la position à prendre sur la ligne `BASE` des soldes), est dans
`.claude/skills/epargne/SKILL.md`.

**Un snapshot en retard est annoncé.** Les deux snapshots reportent leur dernière
valeur sur toute date postérieure, donc un chiffre périmé se lit exactement comme un
chiffre à jour : le 22.09, le 3a affichait une valeur vieille de six semaines étiquetée
« au 21.09 ».
Le panneau signale désormais (`savings._stale_notes`, `[data-stale]`) toute poche dont
les données s'arrêtent plus de `STALE_DAYS` = 7 jours avant la fin de la fenêtre — un
week-end plus un férié laissent quatre jours sans cours, jamais sept. Mesuré contre la
fin de la fenêtre et non l'horloge : une fenêtre ancienne n'est pas en retard, et un
ledger lui-même en retard est un autre sujet. Le 3a n'est figé que quand sa dernière
lecture *et* ses cours s'arrêtent : des cours prolongés font avancer l'estimation.

## La poche crypto (Revolut)

`crypto.py` lit le relevé crypto de Revolut (`inbox/revolut/crypto/`) et en fait une
poche du `SavingsBook`, au même titre qu'IBKR et le 3a.

- **Quantités.** L'export imprime les chiffres significatifs sans la virgule
  (« 1,234,567 » pour 0.01234567 ETH). Une transaction porte prix et valeur : la virgule
  est placée au plus près de valeur / prix, ce qui est exact.
- **Staking.** Une récompense n'a ni prix ni valeur. Sa virgule est placée au plus près
  de la récompense attendue — montant staké × rendement × jours depuis la précédente —,
  le rendement étant ajusté (médiane) sur les récompenses elles-mêmes jusqu'à
  stabilité. Une monnaie payée à intervalle fixe (SOL, par epoch) sort nette ; une plus
  dispersée (ETH) peut garder ~1 récompense sur 7 ambiguë d'un facteur 10. Une quantité lue dans l'app (`--crypto-qty
  ETH=…,SOL=…`) recale le total exactement, et reste dans le snapshot pour les
  captures suivantes. La pastille « staking estimé » le dit tant que ce n'est pas fait.
- **Valeur.** Clôtures quotidiennes Binance en USD × change BCE (frankfurter.app), sans
  clé, depuis le premier achat ; figées à la capture comme les autres snapshots.
  CoinGecko a été écarté : son API publique ne sert pas plus de 365 jours.
- **Flux.** Un achat ou un coin reçu est un apport, une vente ou un envoi un retrait,
  une récompense du rendement. L'achat payé en euros Revolut sort du cash : c'est
  pourquoi le cash de l'épargne compte désormais les soldes EUR/GBP convertis
  (`analysis.cash_points(…, rate)`), faute de quoi le total lisait chaque achat comme un
  gain. Le solde du tableau de bord, lui, reste la chaîne CHF imprimée.

## Les repères, au choix

Le bandeau compare la performance à des indices choisis dans un menu (`?bench=`, clés
séparées par des virgules, `none` pour aucun ; sans paramètre, MSCI World et SMI). Ils
viennent de `benchmarks.py` : MSCI World, S&P 500, Nasdaq 100, SMI, Euro Stoxx 50,
émergents, or, bitcoin, ether — clôtures Yahoo Finance × change BCE, capturées par
`--benchmarks`. Le menu (une popover, une feuille du bas sur le téléphone) coche les
repères puis les applique d'un coup, en réécrivant `?bench=` : un repère pas encore
capturé est grisé, avec la commande qui le capture.

**Dividendes réinvestis.** Un indice de prix laisse les dividendes dehors : face à des
fonds qui capitalisent, la comparaison flattait chaque poche — mesuré sur 12 mois, le
SMI gagnait 3 points avec ses dividendes, l'Euro Stoxx 50 2,8, le MSCI World 1,8. Chaque
entrée est donc lue en rendement total, depuis l'instrument qui le donne proprement :

| Repère | Lu sur | Pourquoi |
|---|---|---|
| S&P 500 | `^SP500TR` | l'indice total return lui-même |
| Euro Stoxx 50 | `SXRT.DE` | ETF capitalisant : son cours contient les dividendes |
| MSCI World, Nasdaq 100, émergents | `URTH`, `QQQ`, `EEM` | cours ajusté des dividendes (`adjclose`) d'un ETF distribuant |
| SMI | `SMICHA.SW` | idem ; l'ETF iShares (`CSSMI.SW`) a été écarté : Yahoo y liste chaque dividende deux fois (+19,6 % pour 2025 au lieu de ~17,5 %) |
| or, bitcoin, ether | `GC=F`, `BTC-USD`, `ETH-USD` | ne versent rien : le cours est le rendement |

Le rendement d'un ETF est net de ses frais (0,1 à 0,6 % par an) — ce qu'un investisseur
touche de toute façon. Les proxies du 3a (MSCI World en CHF, SMI) sont des séries de
prix : ils ne servent plus de repère que si le catalogue n'est pas capturé, et le bandeau
les marque d'un astérisque (« prix seul »). Un snapshot capturé avant le changement
(`bases` absent) est lu comme des prix, et un indice dont la recapture échoue garde sa
série *et* son étiquette : une série de prix n'est jamais rebaptisée rendement total.
Des repères qui s'arrêtent plus d'une semaine avant la fin de la fenêtre sont signalés
comme les poches (`_stale_benchmarks`).

## Versements et valeur

Sous la courbe, le panneau « Versements et valeur » compare ce qui a été versé dans le
portefeuille à ce qu'il vaut, point par point (`api/savings._invested`). Le portefeuille
regroupe les poches investies, IBKR, 3a et crypto ; le cash Swissquote n'y entre pas, car
un salaire n'est pas un versement. Si une poche est choisie au-dessus, elle est montrée
seule. Le versé est cumulé depuis le tout premier flux de la poche, pas depuis le début
de la fenêtre : sur un an, il compterait sinon pour rien tout ce qui a été versé avant.
L'écart entre les deux courbes est la plus-value. Le versé est dessiné en escalier
pointillé : il ne bouge qu'aux versements.

## Sur la période ou par an (`?rate=`)

Le bandeau et la table « Par poche » donnent leurs rendements sur la période
(`?rate=period`, défaut) ou **par an** (`?rate=annual`), le choix à côté de TWR / MWR et
gardé dans l'URL comme lui (`VIEW_KEYS` de `frontend/src/lib/url.ts`). Par an seulement à partir d'un an d'historique : en
dessous, un taux annuel extrapole (un bon mois s'affichait à plus de +100 %/an), donc le chiffre
de la période reste à l'écran et le dit (astérisque dans la table, mention dans le
bandeau). Une poche plus jeune que la fenêtre est annualisée sur sa propre durée
(`SavingsBook.summary`, `twr_pa` / `mwr_pa`) : la crypto n'a pas eu les années de la
fenêtre pour faire son rendement. Les repères suivent le même choix.

## L'effet du timing (MWR − TWR)

Le TWR mesure ce qu'ont fait les placements, quel que soit le moment des versements ; le
MWR ce qu'a fait l'argent réellement présent. L'écart est le timing seul — la « chance
des flux » : positif, les versements sont arrivés avant les hausses ; négatif, avant les
baisses. Colonne « Timing » de la table, ligne sous la performance du bandeau, en points
(par an dans la vue annuelle) et en francs : le gain réel moins ce que le TWR aurait
donné sur le même capital moyen (Dietz modifié, le dénominateur de la contribution), pour
que les deux se lisent pareil (`savings._timing`).

## Réserve, plafond 3a, déclaration d'impôts

Trois questions que la table « Par poche » pose sans y répondre.

- **La réserve** (`savings._reserve`) : les comptes courants divisés par les besoins
  d'un mois — le bucket Need des 12 mois entiers avant la fin de la fenêtre, en
  **moyenne** (impôts et primes annuelles sont des besoins, payés en quelques mois ; une
  médiane les effaçait). Repère usuel 3 à 6 mois ; au-delà de 6, le montant qui ne
  rapporte rien est nommé — c'est lui que la colonne totale dilue. Moins de trois mois
  d'historique : rien.
- **Le plafond 3a** (`fiscal.pillar3a`) : le maximum déductible d'un salarié affilié à
  une caisse de pension (OPP 3, art. 7 — table `PILLAR3A_CEILING`, à compléter tous les
  deux ans ; une année absente reprend la dernière et le dit), contre les versements de
  l'année : le journal finpension, puis les virements « Prévoyance 3a » du ledger datés
  après la fin du journal. Ce qui reste, à créditer chez la fondation avant le 31.12, et
  les lacunes depuis 2025, rachetables dans les dix ans (OPP 3, art. 7a).
- **La fortune au 31.12** (`fiscal.year_end`, repli « Pour la déclaration d'impôts ») :
  chaque compte et devise à son solde imprimé du 31.12 (une chaîne vue plus tard compte
  son solde d'ouverture, comme `cash_points`), IBKR à sa NAV avec parts et liquidités,
  la crypto ; les dividendes, intérêts et impôt à la source US de l'année (journal IBKR) ;
  le 3a à part, hors fortune imposable, avec ses versements déductibles. Ce sont les
  valeurs de l'app, pas les cours de fin d'année de l'AFC : proches, et le panneau le dit.
- **L'année en cours, estimée** (`fiscal.year_to_date`, `year_end(..., day)`) : les
  mêmes chiffres au dernier jour du relevé, pas à aujourd'hui — les soldes bancaires
  s'arrêtent là, et une NAV IBKR prise cinq jours plus tard additionnerait deux dates.
  Revenus et versements 3a comptés jusqu'à ce jour. Cartes et colonne en pointillé,
  feuille « Estimation JJ.MM.AAAA » dans l'xlsx. Un revenu encore nul dit le total de
  l'année précédente plutôt qu'un 0 nu : un fonds qui distribue en décembre lit 0
  jusque-là.

## IBKR sans connecteur : le service Flex (`--ibkr`, `--refresh`)

Le connecteur demande une session Claude Code et se déconnecte : l'épargne
vieillissait dès que personne ne lançait `/epargne`. Le **Flex Web Service** d'IBKR
sert un rapport défini une fois dans le portail à quiconque détient son jeton, depuis
un script. `flex.py` le télécharge, le lit et le verse dans `data/ibkr.json` comme une
capture — en n'ajoutant que ce qui est plus récent :

- la NAV du courtier jour par jour → `nav` ;
- positions et liquidités à la fin du relevé → `positions` (une position vendue est
  retirée, sinon sa dernière valeur compterait encore), `cash`, `account` ; le cours
  du fonds → `nav_daily` (chaque jour si la requête a « Prior Period Positions »), que
  lit la décomposition fonds / dollar ;
- versements, dividendes, impôt à la source et intérêts, commissions → l'historique
  importé par `--ibkr-journal`, **après son dernier jour seulement** : un relevé des
  30 derniers jours lu chaque jour ne compte jamais un versement deux fois. Des jours
  que ni l'historique ni le relevé ne couvrent sont signalés, pas devinés. Sans
  historique importé, les versements restent lus dans le relevé bancaire.

**Mise en place, une fois, dans le portail IBKR :**

1. *Performance et rapports → Requêtes Flex → Activity Flex Query → +.* Format XML,
   période « Last 30 Calendar Days ». Sections, tous champs cochés : Account
   Information, Net Asset Value (NAV) in Base, Open Positions (Summary), Prior Period
   Positions, Cash Report, Cash Transactions, Trades (Execution), Conversion Rates.
2. *Paramètres → Paramètres du compte → Rapports → Flex Web Service :* activer et
   générer un jeton (valable un an au plus).
3. Copier `data/ibkr_flex.example.json` en `data/ibkr_flex.json` et y mettre le jeton
   et le numéro de la requête. Le fichier est hors du dépôt ; le jeton n'est jamais
   imprimé ni mis dans un message d'erreur. Ne le donner à personne, Claude compris.
4. `python -m pms --ibkr`.

Le lecteur suit le format documenté par IBKR et est testé sur un relevé inventé
(`tests/test_flex.py`). Il a lu le vrai relevé dès le 08.10, qui a appris deux choses
au format documenté : une requête ventilée par jour répète les positions à chaque date
(seules celles du dernier jour comptent), et la NAV se garde au centime.

**`--refresh`** enchaîne ce qui bouge sans relevé bancaire : IBKR (si Flex est
configuré), les repères, les indices du 3a, la crypto. Chaque étape est indépendante :
une qui échoue le dit et les autres passent. `run.bat` le lance au démarrage avec
`--daily` — une fois par jour ; la journée n'est marquée faite (`data/refresh.json`)
que si toutes les étapes ont réussi, une étape en échec est retentée au lancement
suivant.

**Les indices du 3a viennent aussi de Yahoo** (`benchmarks.proxies`, lancé par
`--benchmarks`) : SMI, EEM, et URTH × USD/CHF, en cours simples comme les séries
qu'ils prolongent. Contrôlé sur septembre 2026 contre les captures IBKR : SMI et EEM
identiques, URTH × le change de clôture de Yahoo à 0,05 % près (le fixing BCE de
16 h s'en écartait jusqu'à 0,5 %). Seules les séances closes sont ajoutées : un point
ajouté n'est jamais réécrit. Il reste au 3a sa valeur lue dans l'app finpension, de
temps en temps (`--3a-value`).

## L'allocation cible (`allocation.py`)

La barre de composition dit ce qu'est l'épargne ; une cible dit ce qu'elle devrait
être. Déclarée par classe d'actifs (les classes de la vue « Type d'actif » : Cash,
Actions, Obligations, Trend-Following, Crypto) plutôt que par compte — la question
est le risque, pas la banque. Le 3a compte avec le reste : l'oublier fausserait la
part d'actions, mais il ne se vide pas à volonté, et le panneau le rappelle.

Le repli « Allocation cible » donne, par classe, la valeur, la part, la cible et
l'**écart en francs** ; une classe non nommée (« Autres ») vise zéro, si bien que les
mouvements s'annulent : ce qu'une classe gagne, une autre le cède. La cible du cash
est traduite en mois de besoins (la réserve). Formulaire ordinaire, `POST
/allocation` : une somme qui ne fait pas 100 % (à 0,5 point près) est refusée avec ce
qui a été tapé. Stockée dans `data/allocation.json`, hors du dépôt, comme les budgets.

**Francs et exposition sont deux colonnes, pas une.** Un fonds empilé (return stacking)
porte, pour chaque franc, un franc d'actions *et* un franc de managed futures
(`exposure: 2`). La barre le
coupe en deux (`asset_split` 50/50) pour que sa somme reste la fortune — juste pour la
fortune imposable et pour ce qu'on achète, mais elle montre la moitié du risque.
`allocation.leverage` ajoute ce qui manque, (exposition − 1) × valeur réparti selon le
même split, et `allocation.exposure` en tire la part de chaque classe en exposition ; le
total dépasse 100 %. La cible et l'écart restent **en francs** : une
cible en exposition ne somme pas à 100 %, et l'écart y dépend de l'instrument acheté —
un franc du fonds empilé ajoute ×2, un franc d'ETF actions ×1. Le panneau affiche donc les deux
côte à côte (colonne « Exposition », note sous la vue « Type d'actif ») et laisse le
choix de l'instrument à l'utilisateur. Rien n'apparaît sans fonds à levier.

## L'export pour la déclaration

Le repli « Pour la déclaration d'impôts » s'exporte en xlsx (`/epargne/impots.xlsx`,
`export.to_tax_xlsx`) : une feuille par 31 décembre, la plus récente d'abord — chaque
compte, la fortune imposable, les revenus IBKR de l'année, le 3a. Mêmes chiffres que
le panneau (`fiscal.year_end`), quelle que soit la fenêtre affichée : un 31.12 est
une date, pas une période.

## Titres non cotés (20.10)

Une action non cotée déclarée sur la page Impôts (`holdings.py`) est une poche de
l'épargne, « Titres non cotés » (`SavingsBook`, slot 4), comptée par défaut dans le total,
la courbe, la composition et les rendements ; « Sans les titres » (`?titres=0`) la retire
de tout, d'un clic. Elle n'apparaît que si un titre est déclaré.

- **Sa valeur** est la valeur fiscale déclarée pour l'année, de son 1er janvier d'entrée ;
  une réévaluation tombe donc au 1er janvier (l'écart entre la valeur de l'année et
  celle de la précédente).
  Une valeur annuelle n'a pas de date plus fine : le saut est une réévaluation, pas un
  mouvement de marché, et la volatilité de cette poche ne veut rien dire.
- **Son arrivée est un apport**, comme l'ouverture d'IBKR : un cadeau ou un achat est de
  l'argent qui entre, pas un gain.
- **Son dividende est son rendement.** Il arrive sur le compte courant, qui le compte
  comme une entrée ; la poche le compte comme une sortie le même jour, si bien que le
  total le lit en gain et que la poche le lit en rendement (TWR : valeur / (valeur −
  dividende)).
- La table de risque garde ses colonnes (IBKR, 3a, crypto) ; le total y inclut le titre
  quand il est compté.
- **Par classe d'actifs, une ligne à part** (courbe et barre), pas dans « Actions » : elle y
  était additionnée, donc comptée mais invisible. L'allocation cible, elle, la range en
  Actions (`titres_in_actions`) : ses cibles nomment des classes, et une part qu'aucune
  cible ne nomme est visée à zéro — elle proposerait de vendre un titre invendable.
- **Plusieurs titres** (une action, une montre…) : la poche ouverte (`?focus=titres`) en
  trace un par ligne et les montre un par un dans sa composition (`titre_<id>` sur chaque
  point de la courbe) ; partout ailleurs, leur somme.
- **Une nature par titre** (`holdings.kind`) : « action non cotée » (défaut) ou « autre
  bien » (une montre, une œuvre). Un autre bien n'a ni payeur ni impôt anticipé (`clean`
  les efface), compte dans la fortune et l'épargne, a sa ligne « Autres biens » par classe
  d'actifs (`titres_other`) et reste **hors de l'allocation** : ce n'est pas une classe du
  portefeuille, et visé à zéro il ferait proposer de le vendre. La poche s'appelle
  « Titres non cotés » tant qu'elle ne tient que des actions, « Hors marché » dès qu'un
  autre bien y entre (`holdings.pocket_name`, servi aussi par `/api/meta`).

## Rafraîchir depuis l'app (26.10)

Le bouton « Rafraîchir » en haut de la page Épargne lance ce que `run.bat` fait chaque jour
au lancement (`--refresh --daily`) : IBKR par le service Flex (s'il est configuré), les
indices de référence et ceux du 3a, l'inflation, la crypto (s'il y a un relevé). Un seul
module pour les deux, `refresh.py` : chaque étape tourne seule, ce qu'elle écrit est gardé
étape par étape, et la page le montre avec les mots de la console. Le Flex prend jusqu'à
une minute : le serveur travaille dans un fil à part (`web/api/fetch.py`), la page demande
où il en est, puis recharge les chiffres. Un second clic pendant un rafraîchissement ne
relance rien.

`data/refresh.json` garde `at`, la dernière fois que tout est passé (le lancement quotidien
saute tant qu'elle a moins de 20 h), et `last`, la dernière tentative avec le résultat de
chaque étape. Aucune étape n'écrit le jeton Flex.
