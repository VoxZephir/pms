# Prévisions de trésorerie et de patrimoine

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

**Le futur vient de deux endroits, tenus séparés comme le ledger et les overrides.**
`data/plans.json` (gitignoré, `plans.example.json` versionné) porte les faits déclarés :
revenu mensuel, ponctuels (date précise — ou mois seul —, libellé, montant, nature), et
les motifs saisonniers ignorés.
Le ledger, lui, *suggère* : une catégorie dont la dépense se concentre sur un même mois
calendaire, deux années de suite, au-dessus de `SEASONAL_MIN_AMOUNT` (1500 CHF) et d'au
moins `SEASONAL_FACTOR` (×2) son mois ordinaire — le mois candidat **exclu** du calcul,
sans quoi une catégorie qui n'existe qu'en décembre se comparerait à elle-même.

**La projection est une petite arithmétique, pas un oracle.** Cash de départ = solde de
clôture CHF ; chaque mois : + revenu (déclaré, sinon médiane de l'historique), − base −
ponctuels. La base est la médiane des mois **dégraissés** de leurs contributions
saisonnières — sinon l'assurance de décembre compterait deux fois, une dans la médiane et
une sur sa ligne. C'est pour ça que le graphique est en pointillé : prévu ≠ observé.

**La projection commence par le reste du mois en cours.** Le relevé s'arrête presque
jamais le dernier du mois, et tout ce qui était planifié pour la fin de ce mois tombait
dans un trou : la première ligne projetée était le mois *suivant*. Le reste du mois est
donc une ligne à part, mesurée contre le ledger et non proratée au jour : revenu et base
habituels, moins ce que le mois a déjà encaissé et dépensé — un salaire déjà versé
n'ajoute rien, un mois déjà au-dessus de sa dépense habituelle n'ajoute plus rien. Elle
est annoncée « reste du mois » plutôt que de se faire passer pour un mois entier, et elle
n'existe que si le relevé s'arrête en plein mois. La même règle couvre un ponctuel sans
date du mois courant : s'il porte la provenance de sa suggestion et que le ledger a déjà
porté la dépense, il ne re-prédit pas la facture.

**L'horizon est de la vue, pas des données** (`?months=N`, 1..480, défaut 12). Il voyage
comme `?wealth=`/`?scale=` : porté par `_previsions_url` (seg, actions de formulaires,
redirect du POST), tombé quand il vaut le défaut, contrôlé par un vrai formulaire GET
dont l'action ne porte pas de clé `months` — la valeur du select est la seule qui
atteigne le serveur, et le handler JS de POST laisse les formulaires GET naviguer. Un
horizon qui n'atteint pas le mois d'une suggestion la retire de la liste (elle n'a pas de
cible), et l'ancre d'une suggestion est la première occurrence **future** — la ligne
« reste du mois » est le mois qui vient de passer, y ancrer « chaque mai » re-prédirait
la facture du ledger et masquerait celle de l'année suivante (l'ombre portée est indexée
sur le numéro de mois, pas l'année). Au-delà de 12 mois les libellés passent en années
(`months_label`) : « 480 mois » se lirait comme un numéro de téléphone.

**Confirmer une suggestion = la déclarer.** L'entrée garde sa provenance (`seasonal`),
pour qu'un renommage (« Santé & assurance » → « Assurance maladie ») ne fasse pas
compter la même dépense deux fois : une suggestion est masquée par une déclaration du
même mois qui porte son nom ou sa provenance. Une suggestion confirmée quitte aussi la
liste « Suggérés par l'historique » — l'y laisser permettrait de la confirmer deux fois,
et deux déclarations de la même ombre portée comptent deux fois.

**Le point le plus bas inclut aujourd'hui.** Si la projection ne descend jamais sous le
cash actuel, le plancher est « aujourd'hui » — « tu ne descends jamais sous ce niveau »
est la réponse honnête, pas le premier mois projeté.

**La courbe de patrimoine traverse aujourd'hui.** `/previsions` portait une courbe de
*trésorerie* et le tableau de bord une courbe de *patrimoine*, chacune sur sa moitié du
temps : rien ne répondait à « où j'en serai ». Le panneau `p-wealth` met les deux sur un
seul axe — douze mois mesurés (`_evolution_row`, le même constructeur que la courbe
d'épargne, donc les deux panneaux ne peuvent pas se contredire), puis douze projetés. Trait
plein à gauche, traitillé à droite, une règle verticale à la jointure. **La jointure est un
point partagé, pas deux points confondus** : le dernier niveau observé *est* le niveau de
départ de la projection, et le dessiner deux fois les inviterait à diverger d'un arrondi.

**La courbe a trois vues, deux côtés de l'impôt sur la fortune** (`?wealth=all|taxable|sheltered`).
Un 3a sort de la fortune imposable jusqu'au retrait ; le solde de banque et le courtage,
non. C'est le même argent vu deux fois, comme le stack de la timeline — et la moitié
mesurée et la moitié projetée se découpent de la même façon, sinon la courbe ferait un
escalier à la jointure pour la seule raison du filtre. La vue « hors impôt » ne tient
aucun compte courant : la poche 3a n'a pas de cash, et seule une contribution déclarée
vers elle y entre — un virement vers le courtage ne doit pas la faire grossir.

**Le taux de rendement n'est jamais inventé.** `plans.json` porte `rate`, déclaré par
l'utilisateur ; `None` n'est pas 0 % — c'est l'app qui refuse de choisir, et les placements
restent figés à leur dernière valeur en le disant. La bande est ±1 écart-type de la
volatilité **mesurée sur les poches elles-mêmes** (`risk_stats`, sur les placements seuls —
inclure le solde Swissquote lirait un salaire qui tombe comme du risque de marché),
élargie en √t. C'est ce qui empêche un trait unique de se lire comme une promesse. Le
taux s'applique aux **poches seules** : la ligne de cash est de l'arithmétique sur
chiffres déclarés et ne capitalise jamais — mettre de l'intérêt inventé dans le seul
chiffre de la page qui vient tout droit de la banque serait un parjure. Le champ vit à
côté de la courbe qu'il déplace (changer un nombre et remonter voir l'effet n'est pas une
façon d'explorer une hypothèse) et se replie dans la section plan quand aucun snapshot de
courtage ne permet la courbe : il ne disparaît jamais.

**Le taux peut être un barème, pas un nombre seul** (`rate_segments`, listes `[mois,
taux]` comme `ignored_seasonal`). Chaque segment couvre les lignes projetées suivantes,
et au-delà des périodes annoncées le dernier taux déclaré continue de s'appliquer — un
segment unique vaut exactement l'ancien `rate`, la migration est invisible. Le taux est
annuel mais composé mensuellement : −50 % par an, c'est ×0,5^(1/12) ≈ −5,6 % par mois, et
après 36 mois il reste un huitième — le formulaire le dit. `rate` reste écrit au premier
segment pour un lecteur plus ancien du fichier.

**La volatilité aussi se déclare** (`vol`, fraction ; `None` = mesurée, le défaut).
Déclarée 0 %, aucune bande n'est dessinée — une bande plate n'a rien à dire, et le texte
d'aide le dit. Hors de [0, 100] %, une saisie est refusée et une édition à la main est
démue en `None` : une volatilité négative inverserait la bande, une > 100 % l'exploserait.
La même valeur effective sert aux trois vues fiscales — le même argent vu deux fois ne
dessine pas deux bandes.

**Un scénario de plan est un plan entier sous un nom** (`plan_scenarios` et
`active_scenario` dans `plans.json`) : revenu, dépense mensuelle, ponctuels, versements
programmés, barème, volatilité, suggestions ignorées. Les champs du haut du fichier sont
la **copie de travail du scénario affiché** : chaque formulaire de la page la modifie, et
`save()` la recopie dans le scénario actif. Changer de scénario range d'abord celle-ci,
puis charge l'autre — rien de tapé ne se perd, et un fichier sans scénario se lit comme
avant (un plan sans nom). « Enregistrer sous » copie le plan affiché et bascule sur la
copie : on part d'un plan qui marche et on le varie. Supprimer le scénario affiché garde
ses champs, sans nom — rien ne change à l'écran. Le tableau « Scénarios » projette chacun
sur le même horizon et répond aux questions d'un scénario : point bas du cash, cash à
l'horizon, versé aux placements, patrimoine (les poches partent de leur valeur du jour et
croissent au barème de chaque scénario, dans la vue de patrimoine affichée). Les scénarios
de marché ci-dessous restent communs à tous : ce sont des hypothèses sur les marchés, pas
sur sa vie.

**La section se lit du coup d'œil au détail** (`Scenarios` dans
`frontend/src/pages/Previsions.tsx`, `comparison` dans `/api/previsions`) : un graphique met le cash de chaque plan sur **un seul axe**
(le plan affiché en trait plein et plus épais, les autres plus légers mais dans leur
propre teinte, nommés en bout de ligne, chaque point bas marqué), puis une carte par
plan — qui sert aussi de légende : même couleur que sa ligne —, enfin le tableau, replié.
La couleur suit **l'ordre de création**, pas l'alphabet : un scénario ne doit pas changer
de teinte parce qu'un autre a été nommé avant lui ; au-delà de huit, gris neutre. Chaque
carte se lit contre le plan affiché (« +1'200 vs affiché ») : c'est lui qu'on modifie.

**La dépense mensuelle se déclare** (`spend`, `None` = la médiane de l'historique). La
médiane court sur tout le relevé et retarde sur un nouveau loyer : après un changement de
loyer, elle sous-estime les derniers mois complets pendant des mois. Le KPI dit
laquelle est projetée et rappelle l'autre.

**Un virement vers les placements n'est pas une dépense habituelle.** Le ledger range le
virement IBKR dans les dépenses (bucket `Save`) ; dans la baseline, une série de 1'000/mois
déclarée serait comptée deux fois — dans la médiane et sur sa ligne. `baseline`,
`monthly_profile`, `seasonal_one_offs` et le reste du mois en cours écartent donc les
catégories du bucket `Save` (`_saved`).

**Une confirmation ne masque que son année.** Confirmer l'assurance de décembre 2026
masquait la suggestion de *tous* les décembres : sur un horizon de deux ans, décembre 2027
n'avait plus d'assurance. L'ombre est maintenant indexée sur le mois projeté, comme le
dit la règle (« une déclaration du même mois »).

**Les scénarios de marché sont des presets, pas des modes** (`scenarios` dans `plans.json` :
nom → `{rate_segments, vol, months}`). Appliquer un scénario **copie** ses valeurs dans
les champs vivants — ce qui atterrit dans le fichier est octet pour octet ce que la saisie
manuelle aurait écrit, et tout reste éditable ensuite. `months` est l'horizon que la forme
du scénario suppose : l'appliquer règle aussi la longueur de vue (`?months=`), sinon une
« décennie perdue » de 15 ans se rendrait sur un axe de 12 mois. Un scénario enregistré ne
rend pas le plan non vide (il ne change rien tant qu'il n'est pas appliqué) ; une
contribution, si. Trois scénarios proposés (`BUILTIN_SCENARIOS`) sont des **exemples de
forme, pas des conseils** — l'app propose, appliquer est la déclaration, et la vol y reste
toujours `None` (mesurée) : la dispersion est une observation sur les poches de
l'utilisateur, pas une hypothèse à mettre en modèle. **La « Décennie perdue » est mesurée,
pas inventée** : −11,8 %/an pendant 102 mois est le CAGR qui mène au creux de −65,6 %
(pic 2000-09-07 → creux 2009-03-09, S&P 500 total return × USDCHF), et +20,27 %/an
pendant 69 mois celui qui en revient (recouvrement 2014-12-19) — l'ancien barème
(−2 % deux ans puis +3 % huit ans) était une décennie qui *gagne*, l'inverse du nom.
Le formulaire de taux et l'application passent par le même `Plan.set_rates`, qui préserve
la volatilité déclarée : éditer le barème ne doit pas effacer silencieusement la vol tapée.

**Une série de versements se déclare comme un ponctuel qui se répète**
(`contributions` : poche, montant, cadence mois/trimestre/semestre/année, durée, départ).
Chaque échéance devient un virement déclaré sur sa ligne — la trésorerie le soustrait, la
poche le reçoit, le total n'est pas touché : la même mécanique que le ponctuel, sans
nouvelle arithmétique. Le départ vide vaut « premier mois complet » : la ligne « reste du
mois » est la seule que le ledger couvre aussi, et y charger un virement doublerait celui
que le relevé a déjà enregistré. Un départ explicite au mois courant est compté en entier
— comme tout ponctuel sans date ; l'app ne proratise jamais et ne devine rien du libellé.
La note « virements déclarés » compte ponctuels et séries confondus, une seule fois par
échéance.

**Une série peut se limiter à certains mois de l'année** (`in_months`, 1-12, absent =
toute l'année). « Chaque mois, de mai à décembre » : pas de virement de placement en début
d'année, quand les impôts tombent, puis tous les mois. Le filtre s'ajoute à la cadence (une
échéance qui tombe sur un mois exclu est sautée, pas décalée) et la durée reste en mois du
calendrier. Les douze mois cochés valent « toute l'année » et sont stockés sans le champ,
la forme d'avant ; aucun mois coché est refusé plutôt que lu comme « toute l'année ». Le
formulaire : « toute l'année / certains mois seulement », puis douze pastilles à cliquer
(Maj+clic pour une plage) et quelques raccourcis (sans janv.–avril, un semestre,
décembre seul). La phrase de la ligne (« de mai à décembre », « d'avril à décembre »,
« en mars, juin et septembre ») vient du serveur (`plans.months_phrase`).

**La courbe de patrimoine a une échelle log** (`?yscale=log|linear`, défaut linéaire).
C'est le mode d'un horizon à plusieurs décennies. Le log ne s'applique que si toute
valeur dessinée (totaux **et** bords de bande) est strictement positive — le total d'une
poche peut être nul ou négatif, et log d'un nombre non positif n'existe pas : la géométrie
retombe en linéaire et le dit, plutôt que d'inventer un plancher. L'infobulle, elle,
affiche toujours les vrais francs, pas les logarithmes.

**L'infobulle du patrimoine montre la bande** : chaque point projeté porte ses bords
±1σ dans le payload (le point observé n'en a pas — leur absence *est* le signal), issus
des mêmes listes que le polygone, donc l'infobulle ne peut pas contredire le dessin.
Ligne omise quand la bande est dégénérée (vol 0, jointure, poches vides) — une bande
d'épaisseur nulle n'a rien à dire.

**Le tableau « Mois par mois » se lit en barres avant les chiffres** (`previsions/Months.tsx`).
Chaque mois est une barre qui part du milieu : à gauche ce qui sort, empilé depuis l'axe
(dépense courante, ponctuels, virements vers les placements), à droite le revenu, sur une
seule échelle pour tout l'horizon — un gros mois se voit gros à côté d'un mois calme.
Quatre couleurs : `--good`, `--unsorted`, `--warn`, et `--s1`, la teinte de la courbe de
patrimoine, pour l'argent qui y part. Sous la barre, les ponctuels nommés (une suggestion
en italique, pastille en pointillé) ; un versement programmé est dit court, une fois par
poche (« → placement 500 ») : il revient chaque mois, et la puce répétée « Versement
programmé (placement) −500 » noyait les vrais événements. Colonnes nommées : net du mois,
cash en fin de mois, patrimoine. L'entête d'un repli dessine le cash de l'année en
petite courbe et donne la variation signée.

**Le tableau « Mois par mois » se replie par année, et par décennie au-delà de quatre
ans** — un horizon de 40 ans ne doit pas vouloir dire 480 lignes à défiler. La première
année (et sa décennie) est ouverte pour garder le proche horizon en vue. L'entête d'un
repli compte chaque nature à part — ponctuels, versements programmés, suggestions : une
série de 1'000/mois n'est pas « 12 ponctuels ». Chaque ligne de mois est appariée à son
point de patrimoine par la clé du mois (`AAAA-MM`), jamais par indice.

**Un ponctuel déclare sa nature : dépense, virement 3a, ou virement de placement.**
Même leçon que les jambes de change dans le ledger, un horizon plus loin : `project()`
soustrait un virement du cash (l'argent part vraiment), `project_wealth()` le remet
dans les poches — sans ça la courbe fait une falaise à chaque versement au 3a. **La
nature est déclarée, jamais déduite du libellé** — deviner « 3a » serait l'app qui
invente une intention. Elle décide aussi du côté de l'impôt sur la fortune où l'argent
atterrit : un ancien booléen `transfer` se lit encore, et vaut « placement imposable »,
la réponse qui garde le total honnête — crier « 3a » sous-estimerait ce que l'impôt
atteint. Elle se change sur place (`set_destination`) plutôt que par
suppression-réajout, qui perdrait la provenance `seasonal` et démasquerait silencieusement
la suggestion confirmée.

**Une date précise garde un ponctuel de fin de mois dans la projection.** C'est ce que la
ligne « reste du mois » a rendu possible : déclaré au 28, un versement reste visible tant
que le relevé ne dépasse pas le 28 ; daté du 3, il sort dès que le ledger le porte — le
compter encore soustrairait deux fois le même argent. Sans date, il reste tant que son
mois n'est pas passé : « à un moment d'août » est encore à venir, et la table le dit
(« mois entier »). La date est la déclaration la plus nette et porte son mois toute seule.

**Le patrimoine se décompose par poche et par classe d'actifs** (`?split=pockets|classes`,
page seulement : la réponse du serveur porte déjà les deux, la bascule ne recharge rien).
`plans.project_pockets` refait l'arithmétique de `project_wealth` poche par poche
(comptes, IBKR, 3a, crypto) : chaque poche investie capitalise au barème déclaré — **un
seul taux pour toutes**, le plan n'en déclare pas par poche — et reçoit les versements
de sa destination (3a → 3a, placement → IBKR). La croissance étant linéaire, les poches
retombent sur la courbe au centime (`test_the_pockets_add_up_to_the_curve`, dans les
trois vues fiscales). Les classes sont les poches **à composition constante** : chaque
poche garde la répartition mesurée aujourd'hui (`_evolution_row`, la même que la barre
de l'Épargne), et l'argent nouveau la suit — l'app ne suppose aucun rééquilibrage. Une
poche vide aujourd'hui qui reçoit un versement n'a pas de composition à suivre : son
argent est « Non réparti », pas deviné. Le graphique empile les parts (pleines mesurées,
plus claires et traitillées projetées, le total par-dessus) ; une part sous zéro ne
s'empile pas honnêtement, elles sont alors dessinées en lignes et la page le dit. Mêmes
teintes que l'Épargne : une poche garde sa couleur d'une page à l'autre.

**« Ce qui fera le patrimoine » est un pont, pas un graphique de plus** (`Contributions`).
D'aujourd'hui à l'horizon, une marche par cause : revenus, dépense courante, ponctuels,
le rendement de chaque poche, et, dans une vue fiscale, ce qui part hors de la vue (un
versement 3a vu depuis l'imposable). Les marches font exactement l'écart. Un versement
du cash vers une poche de la vue n'est **pas** une marche : il sort d'une ligne et entre
dans l'autre, la note le chiffre à part — le compter serait le double comptage des
jambes de change, un horizon plus loin. Le tableau dessous rend compte de chaque poche :
aujourd'hui, versé (sorti, pour les comptes), rendement, à l'horizon, part. Une poche à
zéro qui ne reçoit rien n'y figure pas.

**Créer et modifier un scénario se fait sans quitter ce qu'on regarde**
(`previsions/Scenarios.tsx`). « Nouveau scénario » ouvre une feuille (en bas au
téléphone) : un nom — des idées d'un clic, un nom déjà pris refusé avant l'envoi, et
par le serveur, qui écrasait auparavant le plan du même nom en silence — et **le plan
de départ**, n'importe lequel, pas seulement celui affiché (`plan-save-as` avec `from` :
l'affiché est rangé avec ses saisies, l'autre chargé, puis copié). La création amène
à « Le plan », dont l'entête dit toujours lequel il modifie (« Tu modifies ● Nom »), et
permet d'en changer, de le renommer (`plan-rename` ; nommer le plan sans nom, c'est
l'enregistrer) ou de le dupliquer sans remonter. Chaque carte a son menu : afficher,
dupliquer, renommer, supprimer. **Une suppression s'annule depuis son toast** : le plan
supprimé est gardé à part (`deleted_scenario` dans `plans.json`, un seul, jusqu'à la
suppression suivante) et `plan-undelete` le rend sous son nom, sauf si un autre l'a pris
entre-temps.

**L'horizon et le plan affiché se choisissent à côté du titre**, dans la barre
collante (`shell/PrevisionsPickers.tsx`), comme la période et le compte ailleurs : les
deux décident de chaque chiffre de la page et restent à portée en défilant. Ils lisent
la même réponse que la page (`usePrevisions`, une seule entrée de cache) ; changer de
plan est l'action `plan-switch`, et « Nouveau scénario… » ouvre la feuille du panneau
Scénarios (un évènement, la barre ne la porte pas).

**Le rendement et la volatilité se lisent avant de se saisir** (`previsions/Rates.tsx`).
Le barème est dessiné le long de l'horizon : un bloc par période, large comme sa durée,
teinté selon son signe, puis la continuation du dernier taux en hachuré, et la fin de
l'horizon marquée quand le barème la dépasse. Chaque période se saisit avec ses unités
dans le champ ; « 2/4/6 % constant » et « Aucun » s'appliquent d'un clic ; le bouton
d'application ne s'allume que si quelque chose a changé, et le dit. Sous la saisie,
**ce que fait le barème appliqué** à 1'000 CHF sur l'horizon affiché, le taux annuel
moyen équivalent et le creux s'il y en a un — `plans.growth_path`, la même composition
mensuelle que la projection, calculée par le serveur. La volatilité est un choix entre
**mesurée** (sa valeur dite, `vol_measured`, même quand une autre est déclarée) et
**déclarée**.

**Les scénarios de marché sont des cartes** : leur forme (la courbe d'un franc), ce
qu'il devient, le creux, les périodes, et « Appliquer · horizon N ans » quand ils
portent un horizon. Neuf sont proposés (`BUILTIN_SCENARIOS`), chacun avec une `note`
qui dit ce qu'il représente : prudent (2 %), croissance constante (4 %), dynamique
(6 %), une mauvaise année (−17 % : l'ordre de grandeur des actions mondiales en francs en
2022, puis 4 %), krach puis reprise lente (−33 % en un an, cinq ans pour revenir —
testé), stagnation longue (dix ans à 0 %), stagflation, rebond après crise, et la
décennie perdue, seule mesurée sur un chemin réel. Des formes en chiffres ronds, pas
des prévisions : un décimal ferait croire à une précision que personne n'a. La courbe
d'un barème enregistré couvre au moins le début de sa dernière période plus un an,
sinon un barème gardé sur un horizon d'un an cacherait ses périodes suivantes.

**Le rendement se choisit aussi à côté du titre** (`RatePicker`, troisième menu de la
barre) : « 4 % / an · vol 12 % mes. ». Un clic applique un taux constant (aucun, 2, 4,
6 %), un scénario de marché (coché quand le barème appliqué est le sien) ou une
volatilité (mesurée, 0, 10, 15, 20 %) ; le barème par périodes et la phrase en mots sont
dans le panneau « Rendement et volatilité supposés », que le menu déplie et amène à
l'écran (`openSection`). Ce panneau est désormais un panneau de la page, replié par
défaut, plutôt qu'un dépliant caché sous la courbe de patrimoine.

**« Le plan » se lit avant de se modifier** (`previsions/Plan.tsx`). En haut, le mois
ordinaire : revenu, dépense de base, et ce qui reste (`projection.margin`, calculé par
le serveur), chacun avec sa source (« déclaré » ou « historique ») ; un clic sur le
montant le modifie, « Revenir à l'historique » efface la déclaration. Les ponctuels sont
un calendrier, groupés par mois avec leur total, chacun avec la teinte de sa nature
(dépense, vers le 3a, vers le placement) ; un clic (ou le crayon) l'ouvre en entier dans
le formulaire de l'ajout — libellé, montant, date, nature — et l'enregistre à sa place
(`Plan.replace_one_off`, adressé par son ancien couple mois/libellé `was_month`/`was_label`) :
la provenance d'une suggestion confirmée reste, sinon la renommer la ferait reproposer.
Une ligne déclarée pour un mois sans jour garde son mois tant que la date reste vide.
Modifier et supprimer s'annulent depuis le toast. L'ajout s'ouvre à la demande, la nature
en pastilles. Un versement programmé
se déclare comme la phrase qu'il est (« Verser 500 CHF chaque mois pendant 24 mois vers
le 3a, à partir de… »). Les suggestions sont des cartes à confirmer ou ignorer ; les
ignorées se restaurent d'un clic.


## L'indépendance financière (19.10)

`freedom.py`, le panneau « L'indépendance financière ». Trois chiffres et une date :

- **déjà couvert** : le patrimoine entier (compte courant, courtage, 3a, crypto, au dernier
  jour du relevé) divisé par la dépense des douze derniers mois entiers, virements
  d'épargne exclus ;
- **l'objectif** : cette dépense divisée par le taux de retrait, au choix 3, 3,5 ou 4 %
  (`?swr=`). 4 % est la convention de départ de la littérature FIRE (trente ans aux
  États-Unis), 3 à 3,5 % la prudence pour un horizon plus long ;
- **mis de côté** : le revenu mensuel du plan moins la dépense annuelle sur douze ;
- **atteint** : mois par mois, le patrimoine croît au barème de rendement déclaré
  (`plans.rate_at`) et reçoit l'épargne du mois. Sans taux déclaré, la date est celle de
  l'épargne seule, à rendement nul, et la page invite à déclarer un taux : un rendement
  n'est jamais inventé. Au-delà de cinquante ans, la page dit « pas avant 50 ans ».

Trois variantes disent ce qui rapproche la date : 100 ou 500 CHF de plus mis de côté par
mois, 10 % de dépense en moins (qui abaisse aussi l'objectif). Tout est en francs
d'aujourd'hui : un taux déclaré net d'inflation garde la comparaison juste, ce que la note
rappelle.

## Le rendement année par année, et poche par poche (20.10)

**Année par année.** La saisie par défaut du « Rendement supposé » est un taux par année
civile de l'horizon, au centième (« 5,25 », « −12,5 % » : la virgule et le signe moins
typographique sont acceptés, `plans.parse_percent`). Le serveur lit les années sur le
barème (`plans.rate_years`, sur les mois mêmes de la projection, `plans.projection_keys` :
la première année est le reste de l'année du relevé, la dernière s'arrête à l'horizon) ;
une année à cheval sur deux périodes se lit « deux taux » plutôt qu'un taux inventé.
L'action `rate-years` renvoie un taux par année, que le serveur rend en périodes
(`plans.segments_from_years`) : les années voisines de même taux se fondent, et un nombre
d'années qui ne correspond plus à l'horizon (relevé arrivé entre-temps) est refusé, pas
mal relu. Au-delà de la dernière année, son taux continue, comme pour toute période.

Les barres se tirent à la souris ou au stylet (au dixième, l'échelle figée pendant le
geste), se règlent au clavier (↑ ↓ au dixième, Maj pour 1 %) et se touchent au doigt pour
les sélectionner : le doigt garde le défilement de la page. Une sélection (Maj+clic : une
plage) reçoit un taux d'un coup. La grille dessous est la saisie exacte. « Par périodes »
reste l'autre façon de saisir le même barème ; « Constant » le pose d'un clic (1 à 8 %).

**Poche par poche.** Chaque poche investie (IBKR, 3a, crypto, titres non cotés) suit le
barème commun ou a le sien, avec sa volatilité (`Plan.pocket_rates`, `own_rates`). Les
actions du barème (`rate`, `rate-years`, `vol`, `scenario-apply`, `scenario-save`)
prennent `rate_pocket` ; `pocket-own` part d'une copie du commun, `pocket-common` y revient.
Régler une poche qui suit le commun lui donne le sien ; le commun ne bouge pas. La
projection fait croître chaque poche à son barème (`plans.project_pockets`, `schedules`) ;
la courbe est la somme des poches (`plans.wealth_from_pockets`), au centime. La zone est
la somme des ±1σ de chaque poche (les poches prises comme bougeant ensemble, la lecture
prudente) : avec une seule volatilité, c'est exactement l'ancienne. Une poche sans
volatilité déclarée prend celle mesurée sur sa propre série. La comparaison des plans et
l'indépendance financière (`freedom.reach`, `parts`) lisent les mêmes barèmes ; un plan
enregistré garde les siens.

**Les titres non cotés sont dans le patrimoine** (`holdings.py`, à leur valeur déclarée,
dans la vue imposable et l'ensemble, pas dans le 3a ; `?titres=0` les retire, comme dans
Épargne). Par défaut ils **gardent leur valeur** : un rendement de marché sur une action
que personne ne cote serait un chiffre que personne n'a choisi. Leur volatilité n'est pas
« mesurée » : une valeur déclarée qui change une fois l'an mesurerait la déclaration. Les
leur donner un barème (ou « Suivre le barème commun ») est un clic.

**« Baseline Claude »** est un scénario par poche (`BUILTIN_SCENARIOS["baseline-claude"]`,
`pockets`) : appliqué au barème commun, il règle chaque poche qu'il nomme ; appliqué à une
poche, seulement la sienne. Constant, nominal en francs, net de frais : IBKR 8 % (vol
23 % ; des actions avec des managed futures empilées : l'historique long simulé en francs
est nettement au-dessus, un chiffre prospectif se tient en dessous), 3a 4,5 % (14 %),
crypto 5 % (70 %), titres non cotés 12 % (0 ; surtout le dividende, que le revenu du plan,
une médiane mensuelle, ne voit pas, plus un peu de réévaluation), le commun 4 % (12 %).
Le raisonnement est dans le commentaire du code ; ce sont des hypothèses de long terme,
pas une prévision d'année.
