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

**La section se lit de haut en bas** (refonte du 02.10.2026), chaque partie répondant à
une question, toutes sensibles à la fenêtre :

1. **Vue** (`?focus=total|swissquote|ibkr|finpension`) — un sélecteur nommé. Avant, les
   cartes de valeur étaient cliquables sans le dire.
2. **Le bandeau** — ce que vaut la poche à la fin de la période ; de combien elle a bougé,
   **séparé entre l'argent mis (« mis de côté », « versés ») et le rendement** ; la
   performance, TWR ou MWR au choix. La question pour laquelle on ouvre le panneau, sans
   réponse avant.
3. **Composition** — la barre et sa légende chiffrée, déclinable en cinq vues
   (`?split=`). Un encadré répétait les mêmes nombres une troisième fois : supprimé.
4. **Par poche** — valeur, part, apports nets, rendement, TWR, MWR, frais, une ligne par
   poche plus le total : la comparaison pour laquelle la section existe, en un tableau ;
   le détail des frais replié dessous.
5. **Évolution** — Montants · Zoom · Base 100 (un seul sélecteur, anciennement « 0 / Auto »).
6. **Risque et statistiques** — replié : des chiffres pour qui les veut, pas la première
   chose à lire.
7. **Sources** — en français, sans chemins de fichiers.

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

**Un versement n'est pas une performance.** Jusqu'au 24.09.2026, le cash du compte
n'avait jamais bougé : le rapport de deux NAV *était* le rendement, et MWR = TWR. Ce
jour-là, quelques milliers de CHF sont partis de Swissquote vers IBKR (convertis en USD le 28.09 puis
investis en RSST par l'investissement récurrent). Le rapport de deux NAV a lu septembre
à +34 % et douze mois à +77.6 %, contre +7.4 % et +39.3 % pour IBKR ; la performance
totale, elle, comptait le débit Swissquote comme un retrait alors que l'argent restait
dans l'épargne. Désormais :

- **les versements viennent du ledger** (`ibkr.flows`) : un virement Swissquote vers
  Interactive Brokers est un versement vu de l'autre côté — rien à capturer, chaque relevé
  apporte les siens. Un versement venu d'ailleurs se déclare dans le snapshot (`flows`) ;
  `/epargne` le détecte comme un saut de NAV que le `cps` d'IBKR n'explique pas ;
- **le TWR est chaîné point à point**, le versement rejoignant la base au début de son
  intervalle, `v1 / (v0 + flux)` — la convention d'IBKR : +0.90 % le 24.09, le chiffre du
  courtier, là où `(v1 − flux) / v0` donnait +1.13 % ;
- **la performance totale** rajoute le versement côté IBKR au flux du mois : il annule le
  débit Swissquote, puisque l'argent n'a pas quitté l'épargne ;
- **la table de statistiques** retire à chaque colonne la part du versement qu'elle porte
  (`_ibkr_share` : IBKR, USD, RSST en entier ; actions / trend-following à 50 % ; la
  géographie selon la position) ; la MWRR d'IBKR passe à « — » sur une période avec
  versement, faute de XIRR.

Le financement initial du compte (août 2025) précède le ledger et reste inconnu.

**TWR ou MWR, au choix (`?perf=twr|mwr`).** Le TWR dit ce qu'ont fait les placements,
quels que soient les versements ; le MWR ce qu'a fait l'argent du titulaire, chaque
versement pondéré par sa durée (`analysis.xirr`, `money_weighted`, par bissection : la
dérivée s'annule sur les flux d'un compte courant). Les deux sont donnés *sur la période*
dans la carte, annualisés dans la table. Le MWR total compte salaires et dépenses comme
versements et retraits de l'épargne ; le côté IBKR d'un virement annule son côté
Swissquote. Sur 01.10.2025 → 30.09.2026 : épargne totale TWR +10.5 % / MWR +9.5 %, IBKR
+39.4 % / +39.2 %, septembre IBKR +7.4 % / +7.1 % (versé le 24, juste avant un repli).

**Base 100 (`?scale=index`).** Chaque ligne repart de 100 à son premier point : on
compare des performances, plus des tailles — un courtage de l'ordre de 10'000 CHF et un compte
courant quatre fois plus gros sur un même axe ne disaient pas lequel avait fait mieux. En TWR, l'indice est
chaîné versements retirés (`_indexed_rows`, le même `_key_flow` que la table) ; en MWR,
chaque point vaut 100 × (1 + MWR depuis le premier point), versements à leur date
(`_mwr_rows`) — un MWR ne se chaîne pas. En CHF le sélecteur ne change rien au graphique
(une valeur est une valeur) et la légende le dit. **La valeur d'ouverture d'IBKR compte
comme un versement** pour les lignes qui l'agrègent : financée hors du ledger, elle
faisait finir l'épargne totale à 148 en base 100 sur tout l'historique, au lieu de 124.

**Les frais, par poche et par période** (« Frais sur la période ») :

- **Swissquote** — la marge de change et les intérêts négatifs, le chiffre de la section
  custodian ;
- **IBKR** — capturés depuis ses opérations (`costs` dans le snapshot, via `/epargne`) :
  commissions, et l'écart achat/vente des conversions automatiques qu'il passe par paires
  (FXCONV : quelques milliers d'USD achetés à 0.8325, revendus à 0.8316 le 28.09 — un écart de
  l'ordre de 0.1 %). L'historique
  du connecteur s'arrête au 01.10.2025 et le trimestre suivant est vide : l'achat initial
  d'août 2025 n'est pas connu, et la ligne le dit (`costs_known_from`) ;
- **3a** — les frais administratifs forfaitaires trimestriels du journal, désormais datés
  (`fee_entries`), pour qu'une fenêtre dise ce qu'elle a coûté.

Les frais internes des fonds (TER) sont dans les prix des trois poches et sur aucun relevé :
ils ne sont pas estimés, la légende le dit. En chemin : `--finpension` effaçait la
géographie et le nom court déclarés à la main pour chaque fonds — la répartition
géographique avec eux. La régénération les garde désormais.

**L'historique complet vient de l'export « Transaction History » d'IBKR**
(`inbox/ibkr/*TRANSACTIONS*.csv`, `python -m pms --ibkr-journal`, `ibkr_history.py`).
Le connecteur ne voit qu'un an : l'app a cru le compte ouvert en août 2025. Il l'est depuis
le 13.09.2023, et a traversé le krach des tarifs d'avril 2025 — sa pire baisse sur tout
l'historique est **−29.2 %**, pas les −8.85 % de la seule année visible. L'export donne :

- **les versements et retraits depuis l'ouverture** (5 versements, un retrait de quelques
  milliers de CHF le 19.12.2024). Quand l'export est là, il remplace la lecture du
  ledger — lire les deux compterait chaque virement deux fois ;
- **les frais depuis l'ouverture** (≈ 67 CHF) : commissions, écart des conversions
  automatiques passées par paires, retenue US nette par dividende (DBMF 2023 : deux
  prélèvements et un remboursement, 2.69 CHF et non 5.71) ;
- **les positions et la trésorerie jour par jour**, d'où la **valeur reconstruite chaque
  semaine** jusqu'au début de la NAV quotidienne du courtier : parts × clôture du
  vendredi × USD.CHF du vendredi, plus la trésorerie (`ibkr_history.rebuild`, cours
  hebdomadaires capturés dans `prices` via `--capture`). Contrôle : la valeur reconstruite
  le 03.10.2025 est à +0.02 % de celle du courtier. Une semaine qui détient un titre
  sans cours est sautée, pas devinée : l'app lit depuis juillet 2024, quand le compte ne
  détenait plus que du RSST (IUSC, DBMF, VOO, CSPX vendus avant).

**Un versement va au point de valeur qui le montre** (`ibkr._snap`). Le courtier date le
versement de septembre 2026 du 23, Swissquote du 24, la NAV ne bouge que le 24 ; le
retrait du 19.12.2024 apparaît dans le point hebdomadaire du 20. Daté la veille de son
point, un flux se lit comme une chute d'un jour suivie d'un bond — un faux −20 % dans la
pire baisse. Chacun va au premier point qui le suit, ou au suivant si c'est là que la
valeur bouge d'à peu près son montant ; un flux antérieur au premier point est déjà dedans.

**Le retour d'argent du courtier n'est pas un revenu.** Le virement du 20.12.2024 nomme
le titulaire comme expéditeur ; seul le BIC (`IBKRUS33…`) dit Interactive Brokers. Il
était classé « Revenus » — un salaire fantôme de plusieurs milliers de CHF en décembre 2024. Il est
désormais « Épargne & investissement / Retrait de courtage » (`categories.BROKER_BIC`).

**Des repères : MSCI World (CHF) et SMI.** Les proxies du 3a, capturés chaque jour depuis
août 2024, servent aussi d'indices de comparaison (`savings.BENCHMARKS`) ; un indice
capturé dans `ibkr.json` (`benchmarks`, via `--capture`) s'y ajoute — un S&P 500 en CHF,
par exemple. Ils apparaissent dans le bandeau (« sur la même période »), en pointillés
dans la courbe en base 100 (vue par compte seulement : une vue de répartition occupe déjà
toutes les teintes) et comme colonnes de la table de risque, mesurés exactement comme les
poches. Ce sont des **indices de prix** : sans dividendes, ils sous-estiment un ETF
réel d'environ 1,5 % (monde) à 3 % (SMI) par an — l'infobulle le dit.

**La performance IBKR se décompose entre le fonds et le dollar** (`_attribution`) :
`(1 + fonds)(1 + devise)(1 + reste) = 1 + TWR` — le fonds dans sa monnaie (RSST en USD),
le dollar contre le franc, et le reste (dividendes, trésorerie, frais, moment d'un
versement) qui ferme l'écart. Le taux USD.CHF n'est **pas capturé** là où la NAV
quotidienne du courtier existe : il en est **déduit** (NAV = parts × cours × taux +
trésorerie, une seule inconnue) — 0.83122 le 01.10.2026 contre 0.83103 dans le relevé
IBKR ; avant, la série hebdomadaire de la reconstruction. Une copie à la main de 260
cours de change aurait été la seule autre voie, et elle s'était décalée d'une semaine la
fois où elle a été tentée. Lectures sur le ledger réel : sur 12 mois, fonds +32.6 %,
dollar +4.5 % ; au premier semestre 2025, fonds −5.3 % mais **dollar −11.4 %** — pendant
le krach des tarifs, la monnaie a coûté plus que le fonds. Une poche à plusieurs fonds ou
sans cours ne reçoit pas de décomposition plutôt qu'une inventée.

**La NAV IBKR est celle du courtier depuis le 01.10.2025.** La série de performance
(`1Y`) donne la NAV exacte de chaque jour ; capturée le 02.10.2026, elle a remplacé
— exception unique à « une capture n'ajoute que » — la reconstruction d'avant, qui
s'en écartait jusqu'à 5 % (au 30.06.2026). Le prix quotidien
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
qu'elle remplace commençait à la fin du premier mois — octobre manquait — et ne voyait
que 11 points par an. Mesurée contre la NAV quotidienne d'IBKR sur 01.10.2025 →
30.09.2026, elle affichait 30.8 % pour une année à 39.4 %, une pire baisse de −4.2 % pour
−8.9 %, une volatilité de 13.6 % pour 21.9 %. Désormais :

- **aucun taux annualisé sous un an** (rendements annualisés, Sharpe, Sortino, Calmar) —
  un bon mois s'affichait à +136 %/an. Les jours se comptent inclusivement : du 01.10 au
  30.09, c'est un an, pas 364 jours ;
- **une poche plus jeune que la fenêtre est mesurée depuis son premier jour, et l'en-tête
  le dit** (« IBKR (depuis le 04.08.2025) ») : sur tout l'historique, la pire baisse IBKR
  (−8.85 %) ne contient pas le krach des tarifs d'avril 2025 que RSST a traversé (−25 %
  de clôture à clôture), le compte n'existant pas encore ;
- **le 3a est marqué « estimé »** : entre deux relevés il suit des indices de référence ;
- **la dilution du total est dite** : ~65 % de compte courant à rendement nul aplatit sa
  volatilité et flatte son Sharpe ;
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
  ré-ancrer tout août sur la lecture de juillet : la courbe perdait 80 CHF entre le 21
  et le 22. Une lecture plus ancienne que la courbe n'est qu'une observation, elle ne
  remplace jamais la plus récente.

`--status` imprime où s'arrête chaque série, pour ne demander au connecteur que la
suite ; un nom de série de cours inconnu est refusé (une faute de frappe créait une
série que rien ne lit, et le 3a restait figé pendant que la capture se disait réussie).
La marche à suivre, outils du connecteur et pièges compris (USD.CHF horodaté la veille,
la valeur de la position à prendre sur la ligne `BASE` des soldes), est dans
`.claude/skills/epargne/SKILL.md`.

**Un snapshot en retard est annoncé.** Les deux snapshots reportent leur dernière
valeur sur toute date postérieure, donc un chiffre périmé se lit exactement comme un
chiffre à jour : le 22.09, le 3a affichait sa valeur du 8 août étiquetée « au 21.09 ».
Le panneau signale désormais (`savings._stale_notes`, `[data-stale]`) toute poche dont
les données s'arrêtent plus de `STALE_DAYS` = 7 jours avant la fin de la fenêtre — un
week-end plus un férié laissent quatre jours sans cours, jamais sept. Mesuré contre la
fin de la fenêtre et non l'horloge : une fenêtre ancienne n'est pas en retard, et un
ledger lui-même en retard est un autre sujet. Le 3a n'est figé que quand sa dernière
lecture *et* ses cours s'arrêtent : des cours prolongés font avancer l'estimation.
