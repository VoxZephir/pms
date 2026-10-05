# Mécanismes de l'app web : panneaux, redémarrage, sommaire, brush, parts dans le temps, fluidité

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

**Une seule chose empêche le panneau « Engagements sans passage récent » d'être du
bruit.** `recurring_labels` teste la stabilité du *montant*, ce qui suffit au socle
contraint mais laisse passer une cantine fréquentée tous les jours ouvrés. Alerter sur un
déjeuner en retard, c'est apprendre à l'utilisateur à ignorer le panneau. D'où deux
conditions supplémentaires, toutes deux sur le rythme : facturé au plus une fois par
mois (`LATE_MIN_INTERVAL_DAYS`) et régulièrement espacé (`LATE_MAX_JITTER`, l'écart
médian des intervalles contre leur médiane). Le rythme est une **médiane** : la moyenne
serait étirée par le mois manquant qu'on cherche justement.

**Le bouton ⟳ redémarre vraiment le processus.** Recharger le ledger n'a jamais été le
problème — le `Store` le fait déjà sur changement de mtime. Ce qu'il ne pouvait pas faire,
c'est remarquer que le *code* avait bougé sous lui, donc une session passée à modifier le
backend restait servie par ce qui avait été chargé au démarrage. D'où deux choses :

- `python -m pms.web` tourne sous le reloader de Werkzeug par défaut (`--no-reload` pour
  l'éteindre). Modifier un fichier source relance le serveur tout seul.
- Le bouton fait un vrai redémarrage en sortant avec le code que le superviseur respawne
  (`views.system.RESTART_EXIT_CODE = 3`). C'est le mécanisme du reloader lui-même ; tuer la socket
  ou se ré-exécuter sur place se battrait avec l'ancien processus pour le port. Hors
  superviseur (client de test, `--no-reload`, hôte WSGI), `_restartable()` est faux et
  l'endpoint le dit au lieu de tuer le serveur pour de bon — sans ça, la suite de tests
  s'arrêterait au premier appel.

Le navigateur attend un **changement de PID**, pas une réponse : l'ancien processus répond
à `/api/health` jusqu'à l'instant où il sort, donc « le serveur a répondu » n'est pas le
signal. Sans JavaScript, l'attente est un meta refresh (`restarting.html.j2`) — une
redirection enverrait le navigateur sur une socket qui se ferme. Le superviseur n'ouvre le
navigateur qu'une fois : ouvrir depuis l'enfant donnerait un onglet par sauvegarde.

**La bande « D'où vient l'argent » donne des parts, pas des montants.** Chaque colonne
occupe toute la hauteur et se divise selon la part de chaque payeur dans la période. La
question à laquelle elle répond est « qui me payait, et quand ça a changé » ; mettre la
hauteur à l'échelle du montant laisserait un gros mois écraser la transition qu'elle existe
pour montrer — et le combien est déjà au-dessus, en repère d'encaissement sur la timeline.
Une période sans aucune entrée est dessinée **creuse**, même convention que le calendrier :
un gris de remplissage se lirait « un peu ».

Le classement des payeurs est calculé sur toute la fenêtre, pas par colonne, sinon un payeur
changerait de teinte d'un mois à l'autre. Au-delà de `INCOME_SLOTS` (7), la queue se replie
sur « Autres » — 22 contreparties ont versé de l'argent sur ce compte, mais huit teintes
seulement sont validées.

**Le sommaire de gauche vit sur les pages à plusieurs sections.** Le rail `.toc` (fixe,
masqué sous 1480px) liste les sections par ancre et s'allume au défilement ; le
dashboard, `/previsions` et `/reclasser` le portent, chacun avec les sections réellement
rendues — pas de lien vers un panneau absent. Le libellé de chaque entrée est le début du
titre de sa section (`test_toc_labels_mirror_the_heading_text` le verrouille sur les
trois pages).

## Sélection par glissement

L'overlay du brush est injecté par JavaScript, jamais présent dans le markup : sinon il
avalerait les clics qui font marcher le zoom sans JavaScript. Un appui court retombe sur
le lien de la colonne, un vrai glissement sélectionne la plage. `test_the_bands_tile_the_axis_without_gaps`
vérifie qu'aucune plage de pixels ne correspond à aucune date.

L'overlay masque aussi le `mouseover` des colonnes : il relaie donc le survol vers la
colonne sous le curseur, sinon ajouter le brush aurait coûté l'infobulle de détail.

## Évolution des parts Need / Want / Save

Le bloc « Besoins, envies, épargne » donne les parts d'une fenêtre ; ce panneau les
montre mois par mois (`buckets.shares_by_month`, `charts.shares_chart`,
`partials/shares_panel.html.j2`).

**Mesurée avant d'être dessinée, la série brute est très bosselée** (25 mois entiers,
août 24 → août 26) : la part Need des dépenses va de 15 à 89 % d'un mois à l'autre, et
en part des revenus un mois presque sans revenu met Save à −2560 %. Tout le reste
découle de là.

**Deux bases, le même argent** (`?shares=income|spending`, comme le stack de la
timeline). *Revenus* est la définition du bloc d'où l'on vient : les quatre parts font
100 % des revenus, Save = revenus − Need − Want − Non classé, négatif un mois qui a
dépensé plus qu'il n'a encaissé. C'est la seule base où Save existe, et elle n'est pas
bornée. *Dépenses* répartit ce qui a été consommé : toujours définie, 0–100 %, sans
Save. Un mois où la base est nulle n'a pas de part (`None`), pas 0 %.

**L'axe de la base revenus est borné à −100 / 200 %** (`SHARE_FLOOR`, `SHARE_CEILING`).
Un axe étiré jusqu'à −2560 % aplatirait tous les autres mois en une ligne. Un point hors
cadre est posé sur le bord, marqué d'un cercle creux ; l'infobulle et la table disent sa
vraie valeur — le payload du crosshair porte la valeur, pas la position.

**Le lissage est un rapport de sommes glissantes, jamais une moyenne des parts**
(`?smooth=1|3|6|12`). Σ bloc / Σ base sur les N derniers mois : dans une moyenne de
ratios, un mois à 200 CHF de revenu pèse autant qu'un mois de salaire, et c'est
exactement lui qui fait le −2560 %. La somme remonte avant la fenêtre quand le ledger a
ces mois (zoomer sur 2026 ne perd pas les mois qui nourrissent son premier point) ; sinon
la valeur est `None` tant que la fenêtre n'est pas pleine. Les mois bruts restent dessinés
en pâle derrière la ligne lissée : le lissage ne cache jamais la donnée qu'il lisse. Pas
d'EWMA : une somme glissante s'explique en une phrase.

**Mois entiers seulement, quelle que soit la granularité affichée.** Une part
journalière ne veut rien dire, et un mois que le relevé ne couvre qu'en partie bouge pour
une raison qui n'est pas celle du lecteur (le salaire est tombé, le loyer pas encore).
Le premier et le dernier mois du ledger sont donc exclus — le relevé ne commence ni ne
finit presque jamais un premier ou un dernier du mois. Moins de deux mois entiers dans
la fenêtre : le panneau est absent.

**Replié par défaut, ouvert par l'URL.** Un `<details>` natif, qui s'ouvre sans
JavaScript. La présence de `?shares=` le rend ouvert côté serveur : ses options sont des
liens `data-nav`, et un swap qui le re-rendrait replié le refermerait sous le pointeur à
chaque clic. `dash_url()` garde `shares` même à sa valeur par défaut — c'est l'état
ouvert, qui doit survivre à un changement de période — et laisse tomber `smooth=1`. Le
lien du bloc « Besoins, envies, épargne » est un lien simple, pas `data-nav` : le swap
ne suit pas une ancre, et le but est d'atterrir sur le graphique.

Les étiquettes de fin de ligne sont empilées à au moins une ligne d'écart : Want et Non
classé finissent souvent à quelques points l'un de l'autre, et deux noms superposés ne
se lisent ni l'un ni l'autre.

## Fluidité

Mesuré le 22.09 dans Edge, sur le ledger réel, à 1280 × 800 : les pages se chargeaient
vite (60–390 ms, aucun décalage de mise en page) ; ce qui manquait, c'était de se
repérer dans une page de 17 écrans et de sentir la réponse à l'instant.

**Préchargement à l'intention.** Un échange de `<main>` coûtait 92 à 263 ms, surtout
la construction du fragment côté serveur — à peu près le temps entre pointer un lien et
cliquer. Le fragment d'un lien `data-nav` est donc chargé au survol (après 65 ms de
pause : balayer une rangée de liens ne tire pas une requête par lien) ou au focus
clavier, et le clic le trouve prêt : 32 à 61 ms. Le cache vit 10 s, jamais pour la page
déjà affichée, et **se vide à chaque écriture** : toute requête qui écrit (reclassement,
annulation, masse, formulaires, réingestion) passe par `send()` dans app.js, sinon une
vue préchargée avant une correction reviendrait avec ses anciens chiffres.

**Un fondu, pas un clignotement** : 140 ms de View Transitions autour du remplacement,
sauté sous `prefers-reduced-motion` et là où le navigateur ne l'a pas.

**La barre de période se rafraîchit depuis `?fragment=controls`** — le même partial,
sans agrégation (`_controls_context`). Elle rechargeait la page entière : une seconde
construction du tableau de bord à chaque clic.

**Une ancre n'est pas un changement de page.** Un clic sur une ancre du sommaire
déclenche `popstate`, et le gestionnaire re-téléchargeait tout `<main>` pour un simple
défilement — en remplaçant au passage le panneau que l'ancre venait de déplier par une
copie repliée. `popstate` n'échange plus que si le chemin ou la requête ont changé.

**Le sommaire devient une bande sous 1480 px.** Il disparaissait, laissant un laptop
sans rien pour naviguer 17 écrans. C'est maintenant une bande collée sous l'entête, dont
app.js mesure la hauteur (`--header-h` : l'entête passe sur deux lignes en fenêtre
étroite), qui défile de côté et garde la section courante en vue. Les ancres atterrissent
sous l'entête et la bande (`main [id]`, en fin de feuille : la règle de 84 px l'emportait
par ordre de déclaration).

**Les panneaux lus de temps en temps sont repliés** derrière leur titre : cumul annuel,
jours de semaine et mois, pays, custodian — comme l'évolution des parts. Une ancre (le
sommaire, un lien, un `#hash`, un `hashchange`) déplie le panneau visé avant que le
navigateur défile.

**La table du tableau de bord montre 20 lignes** (`COMPACT_PAGE_SIZE`) : à 60, elle
faisait 4,7 écrans à elle seule. `?per=` est porté par sa pagination, ses filtres et ses
puces — sinon la page 2 recommencerait à la ligne 61. La page Transactions garde 60.
Au total : 17 → 11,6 écrans.

**Le calendrier envoie ses chiffres une fois.** Chacune des 730 cases portait un titre,
une liste JSON et un indice d'infobulle : 35 à 47 % du poids de la page. Les chiffres du
jour vivent dans `#chartData`, indexés par date, et l'infobulle les y lit ; chaque case
garde un `aria-label` complet. Sa table jumelle (une ligne par jour de dépense) est
construite par app.js à la première ouverture ; sans JavaScript, `?table=calendar` la
rend côté serveur, dépliée. Tableau de bord 540 → 385 Ko, « Tout » 862 → 575 Ko,
chargement 386 → 260 ms.

**L'app s'ouvre sur le mois en cours** (du 1er au dernier mouvement), titré comme un
mois (« Septembre 2026, jusqu'au 21 »), avec sa revue. Une première version n'y venait
qu'après un import, et encore sur le mois entier précédent : l'utilisateur, relançant
l'app, attendait septembre et tombait sur douze mois. **Après un import** (`web/news.py`),
pendant une semaine, un bandeau annonce le relevé et mène au dernier mois entier qu'il
couvre, jusqu'à ce que ce mois soit affiché. Fermable, mémorisé par import dans le
navigateur (une commodité, donc `localStorage` sous `try/catch`). Un `--reparse` est de
la maintenance, pas une nouvelle.

**L'aide des raccourcis** (`?`, ou le bouton de l'entête) liste les gestes que rien
n'annonce : ←/→, Échap, le glisser sur la frise, le glisser-déposer. Un `<dialog>`
natif ; son bouton est caché dans le markup et révélé par app.js, puisque sans JavaScript
aucun de ces gestes n'existe. Ouverte, elle garde le clavier : Échap la ferme et ne
remonte pas le fil d'ariane derrière elle.

**« Non classé » a sa couleur** (`--unsorted`) : il empruntait le gris des axes, à
1,75:1 en clair et 1,48:1 en sombre. 3:1 est le seuil d'une marque (WCAG 1.4.11) ; un
test le calcule depuis app.css dans les deux thèmes.

**←/→ marchent sur toute fenêtre.** Ils n'existaient que sur une unité calendaire exacte
(jour, semaine, mois, année) : ni sur « 12 mois », ni sur le mois en cours — et ils
s'éteignaient dès qu'un lien avait le focus, c'est-à-dire après presque n'importe quel
clic. Désormais le mois en cours recule sur le mois entier précédent, une unité sur sa
voisine, toute autre fenêtre de sa propre durée (« Précédente » / « Suivante », les
dates dans le titre du bouton) ; seules les flèches du calendrier et les touches
modifiées (Alt+← est le retour du navigateur) leur échappent. Deux pressions de suite
attendent que la barre de période de la première soit en place (`settled` dans app.js) :
sinon la seconde lisait la flèche de l'ancienne barre.

**`/reclasser` groupe ses corrections par nature** — règles, épingles, fusions — chaque
groupe avec son nombre, replié au-delà de dix lignes ; une recherche instantanée (révélée
par app.js) filtre tous les groupes et ouvre ceux où elle trouve. 227 corrections tenaient
en une table de 16 écrans ; la page en fait 2,3.
