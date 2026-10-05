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

**Les scénarios sont des presets, pas des modes** (`scenarios` dans `plans.json` :
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

**Le tableau « Mois par mois » se replie par année, et par décennie au-delà de quatre
ans** — un horizon de 40 ans ne doit pas vouloir dire 480 lignes à défiler. Ce sont des
`<details>` natifs (le pliage marche sans JavaScript), la première année est ouverte pour
garder le proche horizon en vue, et chaque ligne de mois porte son partenaire de
patrimoine attaché côté serveur — jamais apparié par indice.

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
