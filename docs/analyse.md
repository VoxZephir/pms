# Dépenses par mois, profil mensuel et /analyse

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

**Le panneau « Dépenses par mois »** (`p-monthly`) est une ligne par catégorie, avec une
petite barre par mois — « combien part en bouffe ce mois-ci » se lit d'un coup d'œil, là
où une grille de chiffres se lit case par case. Chaque ligne est à l'échelle de son propre
pic (c'est la *forme* de l'année qui compte — le pic de décembre sur la ligne alimentation,
la ligne plate du loyer), et un mois sans dépense est **creux** comme une case vide du
calendrier. Nourri par `analysis.monthly()`, plié au-delà de huit teintes comme la
timeline. Il disparaît sous deux mois de données — un seul mois ne fait pas une série.

**Le profil mensuel vit sur deux pages, un seul gabarit de chart.** Le panneau
« Analyse mensuelle » (`p-analysis`, sur `/previsions`) explique la baseline
qui nourrit la projection ; la page `/analyse` (nav « Analyse », backward
looking, sans fenêtre comme `/previsions`) porte le même profil en panneau
principal et ajoute les stats par catégorie (`plans.category_profile`). Les
deux partagent `partials/monthly_season_svg.html.j2` et
`partials/monthly_profile_table.html.j2` — comme `charts.py`, pas de seconde
copie de la géométrie. Le chart est hoverable comme les autres : le payload
`monthly` de `chartData` porte deux séries d'un point par barre (médiane
brute et hors saisonnier, au sommet de chaque segment), câblées sur le même
`crosshair()` que la projection. Sur `/analyse`, le chip saisonnier du
panneau « Par catégorie » est un `data-nav` vers `/previsions` : la future
facture se déclare là (confirmer la suggestion, ajuster le montant), pas
dans l'historique — le passé ne change pas, seule la prévision le compte.
Le nom de la route ne peut pas être `analysis` : `views/analyse.py` importe
déjà `from ... import analysis`, et une fonction du même nom l'écraserait
silencieusement dans tout le module — ruff (F811) le signale désormais.

L'arithmétique : `plans.monthly_profile()` applique la même soustraction des
pics saisonniers que `baseline()`, mois calendaire par mois calendaire, puis
prend des médianes par mois. Trois colonnes, trois médianes — **la médiane
d'une somme n'est pas la somme des médianes**, donc « brute ≠ retiré + hors
saisonnier » sur une même ligne n'est pas une erreur d'arrondi et ne doit pas
être « corrigée ». Un mois jamais observé est **absent** plutôt que nul : une
barre vide se lirait « n'a rien dépensé en décembre ». La ligne pointillée
est la baseline globale (médiane de tous les mois ajustés, le KPI), dessinée
seulement si elle tombe dans le plot.

**La page `/analyse` a cinq vues du même passé.** Le profil a un mode année
(`?year=`, « Médiane » par défaut) : une seule année à la fois, pour qu'une
hausse d'une année à l'autre se voie brute au lieu d'être aplatie par la
médiane. Une catégorie cliquée (`?cat=`) remplace le profil par sa série
mensuelle réelle (`charts.category_month_chart`), bornée à l'année déclarée
comme le profil — une URL `?year=2025&cat=X` ne mélange pas trois ans — et
le retour ne retire que `?cat=`, le `?year=` survit. L'export
(`/analyse/export.csv|xlsx`) sert les mêmes dicts que la page : le `?year=`
atteint le fichier (la règle « le fichier contient ce que l'écran
montrait »), le `?cat=` non.

**La dispersion est un IQR, jamais un écart-type.** `monthly_profile` porte
`iqr` (Q3−Q1, exclusive ; deux valeurs = leur différence ; une seule = 0) —
la même philosophie que la médiane partout : les factures annuelles étirent
une moyenne, pas une médiane, et un écart-type avec elles non plus.

**La tendance n'est pas une pente annualisée.** Une régression log-linéaire
annualisée transforme un changement de niveau — un déménagement, un nouveau
loyer — en « +824 %/an » : elle extrapole un saut comme s'il était une dérive
mensuelle (mesuré sur le vrai ledger, le loyer genevois donnait ça). La
tendance est donc la **médiane de la seconde moitié des mois observés contre
la première** (`_median_trend`) : un palier se lit comme un palier, une
dérive comme une dérive lente, et le bruit reste amorti par les médianes.
Elle exige ≥ 6 mois observés, et une catégorie **saisonnière n'en a pas** :
sa médiane mensuelle mélange la facture annuelle et les petits mois (l'impôt
2026 réel, ×20, lisait « −94 % ») — son histoire est le chip saisonnier, et
le futur se déclare dans les prévisions, pas dans une pente.

## Budgets

**Un budget est une décision, pas une donnée.** `data/budgets.json` (gitignoré,
`budgets.example.json` versionné) porte un montant mensuel par catégorie ; le ledger ne
le sait pas. La jauge vit dans le panneau « Dépenses par mois » : la **médiane mensuelle**
de la ligne contre le budget (le mois courant est un point parmi d'autres, la médiane est
la réponse stable à « est-ce que je dépasse »), verte sous 100 %, rouge au-dessus, le
dépassement en pourcentage affiché. Édition par formulaires (`/budgets`), sans JS, comme
le plan.
