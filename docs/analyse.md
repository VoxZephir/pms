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

**Le profil mensuel vit sur deux pages, un seul composant.** Le panneau
« Analyse mensuelle » (sur `/previsions`) explique la baseline qui nourrit la
projection ; la page `/analyse` (nav « Analyse », backward looking, sans
fenêtre comme `/previsions`) porte le même profil en panneau principal et
ajoute les stats par catégorie (`plans.category_profile`). Les deux
dessinent `components/MonthlyProfile.tsx` : des colonnes empilées
(`Columns`, hors saisonnier en plein, pic saisonnier en clair, la baseline en
règle pointillée) et la table des trois médianes — pas de seconde copie de la
géométrie. L'infobulle d'une colonne donne les trois médianes du mois. Sur
`/analyse`, le chip saisonnier du panneau « Par catégorie » est un lien vers
`/previsions` : la future facture se déclare là (confirmer la suggestion,
ajuster le montant), pas dans l'historique — le passé ne change pas, seule la
prévision le compte. Dans `api/analyse.py`, aucune fonction ne s'appelle
`analysis` : le module importe déjà `from ... import analysis`, et une
fonction du même nom l'écraserait silencieusement dans tout le module — ruff
(F811) le signale.

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
mensuelle réelle (`drill` dans `/api/analyse`, dessinée par `Columns` avec sa
médiane en règle), bornée à l'année déclarée
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
loyer — en « +800 %/an » : elle extrapole un saut comme s'il était une dérive
mensuelle (mesuré sur le vrai ledger, un changement de loyer donnait ça). La
tendance est donc la **médiane de la seconde moitié des mois observés contre
la première** (`_median_trend`) : un palier se lit comme un palier, une
dérive comme une dérive lente, et le bruit reste amorti par les médianes.
Elle exige ≥ 6 mois observés, et une catégorie **saisonnière n'en a pas** :
sa médiane mensuelle mélange la facture annuelle et les petits mois (un impôt
annuel réel, ×20, lisait « −90 % » et plus) — son histoire est le chip saisonnier, et
le futur se déclare dans les prévisions, pas dans une pente.

## La page Analyse, de haut en bas (19.10)

La page répond à « où part l'argent, et qu'est-ce qui a changé » sans fenêtre, comme
avant. Tout ce qui suit le profil vient de `lookback.py` et ne compte que des **mois
entiers** (`whole_months`) : le premier mois du relevé commence en cours de mois et le
dernier n'est pas fini — l'un et l'autre se liraient comme des mois sobres.

1. **Quatre chiffres** — un mois de dépense et un mois de revenus (médianes), la part du
   revenu gardée un mois ordinaire (médiane des taux mensuels, pas le taux des médianes),
   et les douze derniers mois entiers contre les douze d'avant.
2. **Le mois ordinaire** — le profil, inchangé ; une catégorie ouverte le remplace par
   **son détail** : médiane, moyenne, le mois le plus cher, le total sur douze mois ; sa
   série ; **année contre année** (une ligne par année, mois calendaire en abscisse — la
   saison et la dérive côte à côte) ; **à qui** l'argent est allé sur douze mois
   (`analysis.top_merchants`, chaque nom mène à la table filtrée).
3. **Ce qui a changé** — chaque catégorie, les `n` derniers mois entiers contre les `n`
   d'avant (`year_change` : douze, ou la moitié de l'historique s'il est plus court, au
   moins trois). Barres divergentes sur une seule échelle, en francs : une hausse à
   droite en rouge, une baisse à gauche en vert, triées par l'ampleur du mouvement. En
   francs plutôt qu'en % : +65 % sur 130 CHF ne pèse pas +10 % sur 6'000.
4. **Par catégorie** — la table d'avant, plus une couleur par catégorie (les sept
   premières par médiane ; la queue n'a pas de teinte plutôt que cinq lignes dans celle
   d'« Autres »), les 24 derniers mois en petites barres (un mois sans dépense est un
   trait, ici c'est un fait), la part des douze derniers mois, la **régularité** :
   régulière (≥ 90 % des mois et un IQR sous la moitié de la médiane — le loyer),
   variable (≥ 60 % des mois), ponctuelle, saisonnière (le chip l'emporte). Sans saison,
   la colonne dit le mois de pointe.
5. **Le rythme du mois** — la dépense cumulée jour par jour : médiane des douze derniers
   mois entiers et bande interquartile, le dernier mois par-dessus, son écart à la
   médiane au même jour. Un mois court garde son total après sa fin.
6. **Les jours de la semaine** — paiements par carte seulement (un loyer tombe le jour où
   la banque le passe), en francs par jour calendaire, week-end en autre teinte.

## Budgets

**Un budget est une décision, pas une donnée.** `data/budgets.json` (gitignoré,
`budgets.example.json` versionné) porte un montant mensuel par catégorie ; le ledger ne
le sait pas. La jauge vit dans le panneau « Dépenses par mois » : la **médiane mensuelle**
de la ligne contre le budget (le mois courant est un point parmi d'autres, la médiane est
la réponse stable à « est-ce que je dépasse »), verte sous 100 %, rouge au-dessus, le
dépassement en pourcentage affiché. Édition dans le panneau même, par `/api/budgets`
(`{category, amount}`, ou `{category, action: "delete"}`) ; un montant à virgule est
refusé avec la raison, pas lu de travers.


## Contre la Suisse (19.10)

`swiss.py`, deux panneaux en bas de la page.

**Ton inflation.** Le panier est fait des engagements à prix fixe d'`upcoming.commitments`
(loyer, primes, abonnements), chacun comparé au paiement d'il y a un an (à six semaines
près) et pesé par son coût annuel : la hausse du panier est celle de la somme, la barre
de chaque ligne sa contribution, et les contributions s'additionnent exactement à la
hausse. Restent dehors les factures qui varient (pas de prix à comparer), les impôts (ils
suivent le revenu), l'épargne (une décision) et les courses (le relevé en a les totaux,
pas les prix). En face, l'indice des prix à la consommation de l'OFS, sur un an glissant,
au mois de la fin du relevé.

**Toi et les ménages suisses.** Le mois moyen des douze derniers mois entiers, groupe par
groupe, contre l'enquête sur le budget des ménages 2023 (ménage moyen de 2,07 personnes)
et contre ce ménage divisé par 2,07. Une personne seule dépense plus qu'une tête de couple,
la vérité est entre les deux ; le pourcentage compare à la personne. Les groupes sans
équivalent net (les achats divers mêlent habits, meubles et électronique) restent dehors
plutôt que d'être forcés ; la santé compte la prime LAMal, que l'enquête range dans les
dépenses obligatoires et le relevé dans la santé.

**L'indice se tient à jour seul (20.10).** `--refresh`, que `run.bat` lance une fois par
jour, essaie les séries publiées (BNS, puis OCDE via FRED : `cpi.SOURCES`) et n'en garde
une que si elle redonne les mois déjà connus de `swiss.CPI_MONTHLY` (dix au moins, à
0,15 point près), lue soit comme des taux, soit comme des niveaux d'indice dont on prend
la variation sur douze mois. Un tableau dont la mise en page a changé, ou une colonne qui
s'avère être l'inflation sous-jacente, est donc écarté au lieu de glisser un chiffre
plausible et faux ; la console le dit, et l'app garde ses chiffres. Le résultat va dans
`data/cpi.json`, qui prolonge et corrige les mois intégrés ; la page dit d'où vient la
série et quand elle a été rafraîchie. Le lecteur n'a pas pu être essayé contre les vrais
sites depuis l'environnement où il a été écrit (réseau fermé) : le premier `--refresh`
dira lequel passe.

**Les chiffres publics sont copiés dans `swiss.py`** avec leur source et la date de
lecture : l'app ne demande rien à un tiers en marchant. Ils ont été lus dans les
communiqués de l'OFS le 19.10.2026, pas dans les tableaux eux-mêmes : à confronter aux
tableaux liés, et à mettre à jour à chaque publication (l'indice chaque mois, l'enquête
chaque année).
