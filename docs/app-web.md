# L'app web : architecture React, graphiques, gestes, panneaux

<!-- Détaché de CLAUDE.md le 22.09.2026, réécrit le 17.10.2026 pour l'app
     React : lu à la demande (voir « Où lire avant de toucher »). -->

## Qui fait quoi

**Flask calcule, le navigateur dessine.** Chaque page de l'app a son endpoint JSON
dans `web/api/` (`/api/dashboard`, `/api/transactions`, `/api/savings`,
`/api/previsions`, `/api/analyse`, `/api/corrections`, `/api/triage`, `/api/imports`,
plus `/api/period` et `/api/meta` pour la coquille). Ils appellent les mêmes fonctions
d'analyse qu'avant : aucun chiffre n'est calculé en TypeScript. Le front (`frontend/`)
met en page et dessine.

`web/api/encode.py` transforme ce que l'analyse renvoie en JSON : dates en ISO, une
transaction en ligne plate (`key` = `référence:devise`, l'identité des épingles), un
`Statement` jamais expédié entier, un flottant non fini en `null` — le JSON n'a pas de
NaN et le navigateur refuserait toute la réponse pour un seul.

**Le build est versionné** (`src/pms/web/static/spa/`) : `run.bat` sert l'app sans Node.
Node ne sert qu'à modifier le front (`frontend/README.md`). Vite nomme chaque fichier par
le hash de son contenu : les assets sont servis `immutable` pour un an, `index.html` en
`no-cache`, si bien qu'un nouveau build atteint le téléphone au rechargement suivant.
`test_the_committed_build_matches_the_sources` reconstruit dans un dossier temporaire et
compare les noms : une modification de `frontend/src` sans rebuild casse la suite.

Les pages (`/`, `/transactions`, `/epargne`, `/analyse`, `/previsions`,
`/corrections`, `/corrections/tri`, `/importer`, `/jour/<date>`) servent toutes le même
document ; le routeur du navigateur lit l'adresse. Les anciennes adresses redirigent
(`/reclasser` → `/corrections`, `/day/…` → `/jour/…`, `/app/…` → `/…`) : les favoris et
l'icône de l'écran d'accueil continuent de mener quelque part. Une adresse inconnue
répond 404 avec l'app, qui dit « Page introuvable » ; une route d'API inconnue répond
404 en JSON.

## La pile, et pourquoi

| Brique | Rôle |
|---|---|
| React 19, TypeScript, Vite 8 | l'app ; `tsc --noEmit` et Vitest tournent dans la suite (`test_frontend.py`) |
| React Router 7 | **l'URL est l'état** : fenêtre, granularité, vues, filtres |
| TanStack Query | cache des réponses par URL, la vue précédente reste affichée pendant le chargement de la suivante, préchargement au survol des flèches de période |
| Tailwind 4 | les tokens de couleur sont des variables CSS (`styles.css`), redéfinies en sombre : les utilitaires suivent le thème sans variante `dark:` |
| Radix (dialog, popover), vaul, sonner, cmdk | fenêtres accessibles, feuilles du bas sur téléphone, toasts avec « Annuler », palette Ctrl K |
| motion | transitions : chiffres qui roulent, barres qui poussent, cartes qui glissent ; coupées sous `prefers-reduced-motion` |
| d3-scale / d3-shape | la géométrie des graphiques, calculée dans le navigateur à la largeur réelle de l'écran |

Mesuré le 17.10 sur le ledger réel : premier chargement 244 Ko de JS et CSS gzippés,
plus la police (48 Ko), puis plus rien tant que le build ne change pas. Une vue coûte
ensuite son JSON : 4,6 Ko pour le mois en cours, 25 Ko pour douze mois, 44 Ko pour tout
l'historique. Les pages autres que le tableau de bord sont chargées à leur première
ouverture.

## L'URL est l'état

Comme avant : `?from=&to=&grain=` (ou `?preset=`) déterminent la fenêtre, et chaque vue
est un lien. `lib/url.ts` construit les liens :

- `WINDOW_KEYS` (`from`, `to`, `grain`, `preset`) suivent d'une page à l'autre (`pageHref`) ;
- `VIEW_KEYS` (`stack`, `split`, `scale`, `focus`, `perf`, `rate`, `bench`, `shares`,
  `smooth`) suivent un changement de période ;
- `TABLE_KEYS` (`q`, `category`, `bucket`, `dir`, `sort`, `dir_sort`, `per`) restent sur
  les transactions.

Une fenêtre donnée par ses dates efface le préréglage et inversement : les deux ne se
contredisent jamais dans une URL. Le serveur valide chaque clé et retombe sur la valeur
par défaut si elle est inconnue (`views/common.py`) ; il n'y a rien à valider côté client.
Une fenêtre glissante porte le nom de son préréglage (« 12 derniers mois ») plutôt que
deux dates (`api/shell.PRESET_TITLES`).

**Les écritures passent par `send()`** (`lib/api.ts`) : elle vide tout le cache après la
requête. Une vue lue avant une correction ne peut donc pas revenir avec ses anciens
chiffres. Une correction propose « Annuler » dans son toast : le serveur renvoie ce qu'il
faut restaurer (`undo`), comme avant. Un formulaire refusé (plan, budgets, règles
personnelles) reçoit les erreurs par champ, garde ce qui a été tapé, et rien n'est écrit.

## La période

Elle est toujours à portée, dans la barre collée en haut : `‹ titre ›`. Les flèches,
←/→ au clavier et Échap (remonter d'un niveau dans le fil d'ariane) suivent les mêmes
règles qu'avant (`periods.neighbours`) : une unité calendaire avance d'une unité, le
mois en cours recule sur le mois entier précédent, toute autre fenêtre de sa propre
durée. Le titre ouvre le sélecteur : fil d'ariane, préréglages, un mois au choix dans une
année, des dates précises, la granularité. C'est un popover sur ordinateur, une feuille
du bas sur téléphone.

## Les graphiques

Une seule implémentation par forme, dans `frontend/src/charts/` : colonnes empilées
(`Columns`), courbes (`Lines`), calendrier (`Calendar`). La géométrie de `charts.py`
(supprimé) y a été portée, avec ses règles :

- **une série s'arrête où ses données s'arrêtent** : `null` coupe la ligne, jamais
  rembourré (le cumul annuel, le 3a avant son premier relevé) ;
- **les axes** : pas de 1, 2, 2,5 ou 5 × 10^k, choisis pour gaspiller le moins de hauteur
  (`axisScale`, testé dans `scale.test.ts`) ; axe log sur 1-2-5 pour le patrimoine sur
  plusieurs décennies, linéaire dès qu'une valeur n'est pas strictement positive ;
- **huit teintes validées**, jamais une neuvième : au-delà, « Autres » (`palette.py`) ;
- **le calendrier** : du pâle au foncé, le plus foncé est le plus dépensier, dans les
  deux thèmes ; un jour sans dépense est dessiné creux, jamais gris. Sur un écran large,
  une bande de semaines (continue si la fenêtre tient en un an) ; sur un téléphone, un
  petit calendrier par mois, trois de front, parce que 53 semaines feraient des cases de
  6 px impossibles à toucher.

**Gestes** (pointer events : souris, stylet et doigt, le même code) :

- survol, ou premier toucher, affiche les chiffres d'une colonne ;
- clic, ou second toucher sur la même colonne, l'ouvre : un niveau plus fin, ou la
  journée dans une feuille ;
- un glissement de côté sur les colonnes sélectionne une plage ; sur une courbe, il lit
  les points un à un ;
- le défilement vertical reste celui de la page (`touch-action: pan-y` sur le SVG) ;
- au clavier, le graphique prend le focus, ←/→ parcourent les colonnes et Entrée ouvre.

L'infobulle dit toujours la vraie valeur, même quand l'axe est borné (une part à des milliers de % négatifs).
Elle est dessinée hors du panneau (un portail, en `position: fixed`) puis bornée à
l'écran une fois mesurée : les panneaux rognent leur contenu, et une infobulle de huit
catégories sous un graphique de 300 px passait sous le bord bas de la carte.

## Se déplacer dans une page

Le sommaire n'est déclaré nulle part : chaque `Panel` se marque `data-section`, et
`shell/Sections.tsx` lit la page telle qu'elle est dessinée. Un panneau que l'API a
écarté (fenêtre trop courte) n'y figure donc pas, et un nouveau panneau y entre seul.

- Au bureau, « Sur cette page » sous la navigation de la barre latérale ; la section à
  l'écran est marquée en suivant le défilement.
- Une fois la page descendue, un bouton « Haut de page » en bas à droite ; sur le
  téléphone, il porte aussi le sommaire, dans une feuille.
- Aller à un panneau replié le déplie. Le défilement est animé à la main (`glide`) et
  non par le `smooth` du navigateur : motion, en mesurant la hauteur d'un panneau qui se
  déplie, remet la fenêtre où elle était, et chaque remise annulait le défilement natif.
- La section demandée reste marquée jusqu'au prochain geste du lecteur : en bas de page,
  un panneau ne peut pas remonter jusqu'à la ligne, et « le dernier passé » en
  marquerait un autre.

**La barre latérale se replie en un rail d'icônes** (le bouton à côté du logo, ou `[`) :
64 px au lieu de 248, toutes les destinations gardées, nommées au survol, le groupe
« Plus » à la suite derrière un trait. « Sur cette page » et les avis (relevé attendu,
sauvegarde, mise à jour) attendent qu'elle se déplie ; un avis met un point sur le bouton
qui la déplie. Le choix tient au navigateur (`localStorage`, `pms-sidebar-folded`),
comme le groupe « Plus ».

**Trimestre et semestre sont des granularités comme les autres** (`analysis.GRAINS`) :
colonnes « T2 25 », « S1 25 », une fenêtre qui est un trimestre ou un semestre s'intitule
« 2e trimestre 2025 » et ses flèches avancent d'autant. L'auto ne les choisit jamais
(`suggest_grain`) : elles se demandent dans le sélecteur.

## Sur le téléphone

Sous 1024 px, la barre latérale laisse la place à une barre d'onglets en bas :
Accueil, Transactions, Épargne, Prévisions, et Plus pour le reste. Les fenêtres
deviennent des feuilles qu'on ferme en les glissant vers le bas. Le reste suit :

- les zones de sécurité sont respectées (`safe-area-inset`) ;
- les champs sont en 16 px, sinon iOS zoome ;
- les tables deviennent des listes de cartes (`Table`) ;
- les transactions sont groupées par jour, avec le net du jour ;
- les scénarios des prévisions défilent de côté, carte par carte.

**Le corps de page ne défile jamais de côté.** Une carte dans une grille porte `min-w-0`,
sinon un contrôle segmenté de cinq options élargit la page de 34 px. Le test
`test_no_page_scrolls_sideways_on_a_phone` le vérifie sur chaque page à 390 px.

## Panneaux et données

**Une seule chose empêche le panneau « Engagements sans passage récent » d'être du
bruit.** `recurring_labels` teste la stabilité du *montant*, ce qui suffit au socle
contraint mais laisse passer une cantine fréquentée tous les jours ouvrés. Alerter sur un
déjeuner en retard, c'est apprendre à l'utilisateur à ignorer le panneau. D'où deux
conditions sur le rythme : facturé au plus une fois par mois (`LATE_MIN_INTERVAL_DAYS`)
et régulièrement espacé (`LATE_MAX_JITTER`). Le rythme est une **médiane** : la moyenne
serait étirée par le mois manquant qu'on cherche justement.

**La médiane des colonnes de dépenses se demande** (`?median=1`, une clé de vue : elle
suit la période et la granularité). C'est la médiane des périodes affichées, à leur
granularité — par mois, par semaine, par jour —, calculée par le serveur
(`api/dashboard._median`) sur les seules périodes **complètes** : celle en cours et celle
où le relevé commence, ou celles qu'une fenêtre coupe, pèseraient pour avoir moins de
jours, pas pour avoir coûté moins. Moins de trois périodes complètes : pas de médiane, ni
de bouton. Une ligne pointillée sur le graphique, la valeur et le nombre de périodes dans
la légende, l'écart à la médiane dans l'infobulle d'une colonne.

**La bande « D'où vient l'argent » donne des parts, pas des montants.** Chaque colonne
occupe toute la hauteur et se divise selon la part de chaque payeur. Elle répond à « qui
me payait, et quand ça a changé » ; une hauteur au montant laisserait un gros mois écraser
la transition. Le combien est le repère vert des colonnes de dépenses. Une période sans
entrée est creuse. Le classement des payeurs est fait sur toute la fenêtre, sinon un payeur
changerait de teinte d'un mois à l'autre ; au-delà de `INCOME_SLOTS` (7), « Autres ».

**Évolution des parts Need / Want / Save** (`buckets.shares_by_month`). La série brute
est très bosselée : la part Need des dépenses peut aller du simple au quintuple d'un mois
à l'autre, et un mois presque sans revenu met Save à des milliers de % négatifs des
revenus. D'où :

- **deux bases, le même argent** (`?shares=income|spending`). En part des revenus, les
  quatre parts font 100 % et Save est ce qui n'a pas été dépensé, négatif un mois qui a
  dépensé plus qu'il n'a encaissé. En part des dépenses, c'est toujours 0–100 %, sans
  Save. Un mois où la base est nulle n'a pas de part (`None`) ;
- **l'axe des revenus est borné à −100 / 200 %** : un point au-delà est posé sur le bord,
  l'infobulle dit sa valeur ;
- **le lissage est un rapport de sommes glissantes** (`?smooth=3|6|12`), jamais une
  moyenne des parts, où un mois à 200 CHF de revenu pèserait autant qu'un mois de salaire.
  La somme remonte avant la fenêtre quand le ledger a ces mois. Les mois bruts restent
  dessinés en pâle ;
- **mois entiers seulement** : le premier et le dernier mois du ledger sont exclus, et
  il en faut deux dans la fenêtre.

**Panneaux repliés** : cumul annuel, jours de semaine et mois, pays, custodian,
évolution des parts — lus de temps en temps, ils ne coûtent qu'une ligne.

**La recherche lit chaque mot séparément** (`views.common._filtered`). Casse et accents
sont ignorés, et chaque mot doit se trouver quelque part sur la ligne, dans n'importe
quel ordre :

- bénéficiaire, lieu, lignes d'information, catégorie ;
- montant, écrit `1234.50` comme `1’234.50` ;
- date, écrite `14.10.2026`.

Un nombre entier seul est un chiffre : « 20 » veut dire 20 francs, le 20 du mois, octobre
ou 2020, sinon il trouverait toutes les lignes de 2025 et 2026. Le champ coupe la
correction automatique : sur le téléphone, « twint » devenait « twin ». La palette
Ctrl K applique la même règle à ses pages, périodes et catégories ; la recherche dans le
ledger y vient en dernier, toujours proposée.

**L'app s'ouvre sur le mois en cours**, titré « Octobre 2026, jusqu'au 14 », avec sa
revue. Après un import (`web/news.py`, `/api/meta`), pendant une semaine, un bandeau
annonce le relevé et mène au dernier mois entier qu'il couvre. Il est masquable, et le
masquage est mémorisé par import dans `localStorage` (`pms-news-dismissed`, sous
`try/catch`). Un relevé en retard est rappelé sur le tableau de bord et dans la barre
latérale.

**« Non classé » a sa couleur** (`--unsorted`, 3:1 au moins contre la surface dans les
deux thèmes, WCAG 1.4.11). Un test le calcule depuis `frontend/src/styles.css`. Un autre
vérifie que les surfaces contre lesquelles les huit teintes ont été validées n'ont pas
bougé.

## Relire les relevés

« Relire les relevés » appelle `/api/refresh?restart=0` : il ingère `inbox/` et ne
redémarre pas le serveur. `/api/refresh` sans ce paramètre redémarre encore le processus
quand le reloader de Werkzeug le supervise, en sortant avec le code qu'il respawne
(`views.system.RESTART_EXIT_CODE = 3`). Hors superviseur, `_restartable()` est faux et
l'endpoint le dit au lieu de tuer le serveur.

**La mise à jour suit la branche que la copie suit vraiment** (`web/updates.py`,
`_target`). Une copie clonée sur `main` puis mise à jour par `git pull origin
<branche>` a `origin/main` pour amont, qui ne bouge jamais : comparée à lui seul, elle
se disait à jour pour toujours et le bouton n'apparaissait jamais. La cible est l'amont
s'il a du nouveau, sinon la branche distante dont la copie est un ancêtre (une avance
rapide y mène) qui a bougé en dernier ; « Mettre à jour » s'y avance en `--ff-only` et
en fait l'amont. Quand il n'y a rien à installer, la barre latérale le dit (« À jour ·
vérifié il y a 12 min », la branche, ou la raison d'un échec) avec « Vérifier » : un
bouton qui n'apparaît qu'en cas de nouveauté passait pour une fonction absente.

**Une connexion coupée pendant la mise à jour est un redémarrage, pas un échec** (19.10).
Le `merge` réécrit des `.py` ; le reloader de Werkzeug le voit dans la seconde et arrête
le processus — ce jour-là pendant que `apply()` posait encore ses questions à git :
la réponse n'est jamais partie, la page a lu l'erreur réseau comme un échec et ne s'est
pas rechargée, alors que le code était bien à jour. Désormais `apply()` interroge git
*avant* le merge, et la page note le pid du serveur avant d'envoyer : une réponse
perdue (pas une erreur HTTP) la fait attendre un nouveau pid, puis recharger, et
« Mise à jour installée » s'affiche après le rechargement.

**`run.bat` installe git s'il manque** (étape 0). Sans git, l'app tourne mais le bouton
« Mettre à jour » ne peut rien faire : c'est l'obstacle d'une personne qui ne code pas,
pas Python (uv s'en charge). L'étape propose une fois d'installer git par winget ; un
refus est retenu dans `data/no-git`. Une copie venue d'un ZIP (pas de `.git`) devient
une copie suivie de `PMS_REPO` / `PMS_BRANCH`, à la dernière version : `checkout -f`
réécrit les fichiers du dépôt, `data/` et `inbox/` (ignorés) ne sont pas touchés, et
les anciens assets du build sont nettoyés. Cette conversion réécrit `run.bat` lui-même :
elle vit dans un seul bloc entre parenthèses, que cmd lit en entier avant de
l'exécuter, et qui se termine en relançant la nouvelle version — sinon cmd lirait la
suite du nouveau fichier à l'ancien décalage. Pas de `!` dans les messages : l'expansion
retardée les avale. Le dépôt doit être joignable par la personne : public, ou elle
invitée comme collaboratrice (git ouvre alors une fenêtre de connexion GitHub une fois).

## Le tableau de bord, refonte du 19.10

- **« À faire » en une carte** : sauvegarde absente, rupture des soldes, relevé
  attendu, nouveau relevé — une ligne chacun, son action à côté. Trois encadrés empilés
  repoussaient les chiffres sous le pli.
- **Les tuiles** disent contre quoi elles comparent (« vs juin 26 », `previous.label` ;
  des dates quand la fenêtre d'avant n'est pas un mois ou une année), et portent leur
  courbe en miniature : dépenses et revenus de la timeline, le solde.
- **« Le mois en cours »** (`lookback.month_pace`), seulement pour un mois qui est le
  dernier du relevé : la dépense cumulée jour par jour contre un mois ordinaire
  (médiane et moitié centrale des douze derniers mois entiers, la même que le rythme de
  `/analyse`), l'écart au même jour, la **fin de mois probable** — le dépensé plus ce
  qu'un mois ordinaire dépense encore après ce jour, jamais une extrapolation linéaire
  qui ferait d'un loyer payé le 1er un mois à 50'000. Les budgets y sont lus contre la
  part du mois écoulée (un trait), pas seulement contre leur plafond.
- **« Par rapport à … »** (`api/dashboard._versus`) : chaque catégorie contre la
  fenêtre d'avant, en francs, triée par l'ampleur — le pourquoi de la variation de la
  tuile « Dépensé ». Barres divergentes partagées avec `/analyse`
  (`components/Diverging.tsx`).

## Le change, rejoué chez Revolut (19.10)

Le panneau « Ce que le custodian a prélevé » comparait la marge Swissquote (≈ 0.97 %) à
un Revolut à 0 %. Faux en dehors du forfait : le plan gratuit change au taux interbancaire
en semaine jusqu'à 1'250 CHF par mois glissant, puis à 1 %, et à 1 % tout le week-end ;
Premium n'a ni l'un ni l'autre mais coûte 11.99 CHF par mois (page tarifaire fr-CH, lue le
19.10.2026). `analysis.revolut_replay` rejoue chaque conversion du relevé à sa date :
samedi et dimanche à 1 %, la part d'une conversion en semaine qui dépasse ce qui reste du
forfait des 30 derniers jours à 1 %. Le vendredi soir est déjà le week-end chez Revolut ;
une date n'a pas d'heure, le vendredi compte donc en semaine et le rejeu penche du côté
favorable, ce que la ligne dit. Premium est compté avec son abonnement sur la durée
couverte par les conversions. Chaque tarif porte sa date de lecture.

## Le bouton « Mettre à jour » et la branche main (19.10)

Le travail se fait sur une branche, fusionnée dans `main`. Quand la fusion arrive, la mise
à jour qui l'apporte déplace la copie sur `main` (`git checkout -B main origin/main`,
jamais si un `main` local a des commits à lui) ; une copie sur `main` ne suit ensuite que
`origin/main` (`updates.HOME_BRANCH`). Une copie restée sur une branche de travail garde
l'ancien comportement : elle suit la branche distante qui a bougé.

## Le manuel (`/aide`, 27.10)

Une page sous « Plus » : ce que chaque page répond, la période, lire un graphique, le
calendrier, les courbes mesurées puis projetées, corriger une catégorie, les raccourcis,
les questions fréquentes. **Ses graphiques sont les vrais** (`Columns`, `Lines`,
`CalendarHeat`) sur des chiffres inventés et toujours les mêmes (générateur à graine) :
le lecteur essaie le survol, le clic, le glissé sur le composant qu'il retrouvera
ailleurs, et aucun de ses chiffres n'est montré. Une capture d'écran aurait montré ses
données, et vieilli au premier changement d'interface. Les animations (le chemin d'un
relevé, la main qui glisse sur les colonnes) s'arrêtent sous `prefers-reduced-motion`.

`?` ouvre le manuel sur la carte de la page en cours (`nav.helpAnchor`) ; `/aide#graphiques`
ouvre une section comme le sommaire. Une page ajoutée à `NAV` doit avoir sa carte dans
`PAGES` de `pages/Help.tsx`.
