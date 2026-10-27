# Ce qui manque

État au 27.10.2026. L'app fait ce pour quoi elle a été construite : parser, réconcilier,
catégoriser, corriger à la main, naviguer dans le temps, en ressortir les données, prévoir
la trésorerie et le patrimoine (`/previsions`), analyser le passé mois par mois
(`/analyse`), suivre l'épargne hors relevé (Interactive Brokers, 3a, crypto) et comparer
le coût du change aux taux publiés. Deux banques (Swissquote, Revolut) dans un même
ledger, lisible aussi sur le téléphone. 654 tests Python (navigateur compris) et 16
Vitest, aucun écart de solde.

Ce qui suit est classé par ce que ça coûte de ne pas l'avoir, pas par difficulté.
Chaque point nomme le fichier concerné, pour être repris à froid. Pas d'estimation
d'effort en jours : elles ne disaient rien d'utile.

**Fait le 02.08** : prévisions de trésorerie et stats mensuelles par catégorie (panneau
« Dépenses par mois »), budgets mensuels par catégorie (jauges dans le panneau mensuel),
panneau « Épargne » (snapshot IBKR, lié à la fenêtre, TWR/MWR), coût du change comparé
aux références (section custodian), `--forget <sha>` pour oublier un import erroné, et le
test de géométrie du parser
(`tests/test_parser.py::test_columns_sit_in_their_documented_bands`).

**Fait le 08.08** : courbe de patrimoine qui traverse aujourd'hui (mesurée puis projetée,
taux de rendement déclaré jamais inventé, ponctuels marquables « virement »), bucket
`Save` décomposé en versé / non dépensé, accessibilité (étiquette réelle par champ,
focus clavier visible, lien d'évitement, messages d'erreur sur les formulaires par
re-rendu sans session), design (échelles d'espacement et de typographie nommées, mesure
de lecture bornée à 75ch, fin des styles inline dans les gabarits — gardés par test),
jumeaux en table pour les cinq graphiques qui n'existaient qu'au survol (calendrier,
jours de semaine, saisonnalité, pays, comparaison annuelle), **les règles personnelles
s'éditent depuis la page Corrections** (`data/local_rules.json` : liste, ajout avec
validation regex, suppression — le Store surveille le fichier, une règle s'applique à
la requête suivante sans redémarrage), et **la navigabilité** : navigation commune dans
le layout (WCAG 2.4.5, `aria-current="page"`), fenêtre portée d'une page à l'autre sans
session (`page_url`), miettes marquées et fenêtres voisines nommées (« ‹ Avril 2025 »),
badge « Personnalisé » quand aucun préréglage ne recouvre la fenêtre, colonnes et
cellules de graphique nommées au clavier (`aria-label`, `role="img"` retiré des SVG
interactifs), focus géré après chaque navigation (h1, recherche, pagination), roving
tabindex sur le calendrier, flèches ←/→ entre périodes, filtres retirables un par un
(chips ×), pager conforme (nav landmark, pas de lien aux bornes, page dans le titre,
redirect 302 quand `?page=` sort des bornes), état de fenêtre vide avec retour, page
404 avec retour, toc aligné sur les h3. Les snapshots d'épargne ont été recapturés le
08.08 (IBKR : NAV quotidienne exacte ; 3a : valeur relevée dans l'app).

**Fait du 09 au 15.08, commité le 22.09** : page `/analyse` (profil mensuel en médianes,
dispersion en IQR, tendance par moitiés plutôt qu'en pente, mode année, série par
catégorie, export multi-feuilles), barème de taux, volatilité déclarée, scénarios,
séries de versements, horizon jusqu'à 40 ans, échelle log, bande dans l'infobulle.

**Fait le 22.09 — l'outillage autour de l'app** :

- l'ingestion ne relit plus un PDF déjà importé (17,3 s → 0,6 s par lancement ;
  `--reparse` pour forcer) ;
- la suite tourne sans le relevé privé : un relevé fictif de la même forme
  (`tests/synthetic.py`) ; une copie propre passe 387 tests au lieu de 120, et
  `tests/test_real_data.py` garde les vraies données en tests de fumée ;
- `web/views.py` (2765 lignes) et `tests/test_web.py` (3231) découpés par page ;
- ruff dans la suite (règles de bugs) — il a trouvé un backspace invisible qui
  empêchait « Régie » de jamais correspondre ;
- `app.js` testé dans l'Edge installé (Playwright, 12 tests vérifiés par mutation) ;
- `CLAUDE.md` réduit de 47 à 21 Ko, le raisonnement par fonctionnalité dans `docs/`.

**Fait le 22.09 — la fluidité** (mesuré dans Edge sur le ledger réel, détail dans
`docs/app-web.md`) : échanges de vue préchargés au survol (92–263 → 32–61 ms) et
fondus ; barre de période rafraîchie sans reconstruire la page ; sommaire en bande
sous 1480 px, panneaux rares repliés, table du tableau de bord à 20 lignes (17 → 11,6
écrans) ; calendrier allégé (540 → 385 Ko) ; bandeau « nouveau relevé » après un
import ; aide des raccourcis ; « Non classé » lisible en sombre. En chemin : un clic
sur une ancre re-téléchargeait tout `<main>`.

**Fait le 22.09 — après usage** : l'app s'ouvre sur le mois en cours (« Septembre 2026,
jusqu'au 21 ») avec sa revue ; ←/→ marchent sur toute fenêtre et même quand un lien a le
focus (elles n'existaient que sur une unité calendaire exacte) ; `/reclasser` groupe ses
corrections par nature, repliées, avec une recherche (17,9 → 2,3 écrans). Snapshots
d'épargne recapturés : IBKR, et 3a relevé dans l'app, tous deux au
22.09.

**Fait le 23.09** :

- **l'épargne ne vieillit plus en silence** : le panneau annonce toute poche dont les
  données s'arrêtent plus de 7 jours avant la date affichée ; la recapture est une skill
  (`/epargne`) et une commande (`--capture`, `--3a-value`) qui n'ajoutent que les points
  nouveaux et gardent la lecture 3a précédente — les deux erreurs de la mise à jour
  manuelle du 22.09 (`docs/epargne.md`) ;
- **les Twint se trient une touche chacun** : les centaines de Twint sans bénéficiaire sont
  « Twint non identifié » plutôt que « Transferts P2P », et `/reclasser/tri` les
  présente un par un avec les mouvements du jour et les décisions passées au même
  montant, ou par montant récurrent d'un coup (`docs/corrections.md`). En chemin :
  l'envoi en place des formulaires perdait le bouton cliqué.

**Fait le 02.10 — le premier versement IBKR** : un virement parti de Swissquote vers IBKR
a été lu comme de la performance (le mois et les douze mois IBKR gonflés de plusieurs
dizaines de points, et la performance totale qui comptait le virement comme un
retrait). Les versements viennent désormais du ledger, le TWR les retire à la
convention d'IBKR, la table de statistiques aussi ; `/epargne` détecte un versement venu
d'ailleurs. Et la NAV IBKR est celle du courtier sur l'année que le connecteur couvre — la
reconstruction s'en écartait jusqu'à 5 % (`docs/epargne.md`).

**Fait le 02.10 — frais et mesures** : « Frais sur la période » par poche (marge de change
Swissquote, commissions et écarts de change IBKR capturés depuis ses opérations, frais
forfaitaires du 3a datés) ; TWR ou MWR au choix (`?perf=`), sur la carte, la table et la
courbe ; courbe en base 100 (`?scale=index`). En chemin : `--finpension` effaçait la
géographie des fonds, et la valeur d'ouverture d'IBKR se lisait comme un gain dans
l'épargne totale.

**Fait le 02.10 — refonte de la section Épargne** : un bandeau qui répond « combien,
de combien, et dont combien mis de côté vs rendement » ; un sélecteur de poche nommé
au lieu de cartes cliquables sans le dire ; composition chiffrée une seule fois ; un
tableau « Par poche » (valeur, apports, rendement, TWR, MWR, frais) ; risque replié et
recalculé jour par jour (point 7) ; sources en français. Un seul livre derrière tout
(`SavingsBook`), pour qu'aucune partie ne contredise une autre.

**Fait le 02.10 — l'historique IBKR complet** : l'export « Transaction History »
(`--ibkr-journal`) donne versements, frais et positions depuis l'ouverture du compte
(des années plus tôt que ce que le connecteur laissait croire) ; la valeur est
reconstruite chaque semaine jusqu'à la NAV quotidienne du courtier (un écart négligeable
au raccord). La pire baisse IBKR sur tout l'historique est bien plus profonde que celle
de la seule dernière année. Un retrait revenu sur Swissquote n'est plus compté comme un
revenu.

**Fait le 02.10 — repères et décomposition** : MSCI World (CHF) et SMI comparés à
chaque poche (bandeau, courbe en base 100, table de risque) ; la performance IBKR
décomposée entre le fonds en USD et le dollar contre le franc, le taux déduit de la
NAV du courtier (`docs/epargne.md`).

**Fait du 03 au 05.10 — une deuxième banque et la crypto** : l'export CSV Revolut entre
dans le même ledger comme compte secondaire (`Transaction.account`, chaînes de soldes par
compte et devise, virements internes hors dépenses et revenus) ; le relevé crypto Revolut
devient une poche de l'épargne (quantités dont l'export perd la virgule, staking
reconstitué, cours Binance × BCE) ; le cash de l'épargne compte les soldes EUR/GBP, faute
de quoi chaque achat crypto se lisait comme un gain.

**Fait du 05 au 08.10 — l'épargne mesurée plus juste** : repères au choix dans un menu
(`?bench=`, joignable depuis la courbe), puis **dividendes réinvestis** (le SMI
sous-estimé de 3 points par an, le MSCI World de 1,8) ; UPI et contribution de chaque
poche à la performance ; **effet du timing** des versements (MWR − TWR, en points et en
francs) ; **rendements par an** au choix (`?rate=annual`, jamais sous un an) ; mois de
réserve du compte courant ; plafond 3a de l'année et lacunes rachetables ; fortune au
31.12 pour la déclaration. En chemin : le crosshair décalé de la souris sur les courbes
d'inégale longueur, la page Transactions bloquée sur le mois courant, « Non classé »
qui ouvrait dix fois plus de lignes qu'il n'en comptait.

**Fait le 08.10 — la sauvegarde** (point 6) : `--backup`, lancé par `run.bat`.

**Fait le 08.10 — l'épargne sans session** : IBKR par son service Flex (`--ibkr`), les
indices du 3a par Yahoo, et `--refresh` lancé une fois par jour par `run.bat` — la
recapture n'a plus besoin du connecteur. Allocation cible par classe d'actifs, avec
l'écart en francs ; le tableau de la déclaration exporté en xlsx.

**Fait le 15.10 — le téléphone** (`docs/acces-distant.md`, `docs/sauvegarde.md`) :
l'usage change, l'app doit aussi se lire sur le téléphone, n'importe où. Pas de serveur
loué — les relevés resteraient chez un hébergeur — mais Tailscale : le serveur reste sur
127.0.0.1, `tailscale serve` le porte sur le tailnet en HTTPS, et la veille de Windows
est suspendue tant qu'il tourne. Trois gardes remplacent la connexion que l'app n'a pas
(Host de cette machine, écritures de même origine, écoute sur loopback ou le tailnet ;
`--debug` sur loopback seulement). Au doigt : sélecteur de période replié sous 900 px
(le premier écran d'un téléphone n'était que lui), infobulles et réticule par pointer
events, premier toucher qui montre et second qui zoome, frise et courbes lues au doigt
quand le graphique tient en largeur et défilées sinon, reclassement par la poignée ⠿.
Un relevé s'envoie depuis le téléphone (`/importer`) ; l'app s'installe sur l'écran
d'accueil (manifest, icônes). **La sauvegarde est chiffrée** : elle déposait un zip en
clair des relevés dans OneDrive ; `--restore` la relit sans rien écraser.

**Fait le 15.10 — l'inbox ne se remplit plus à la main** (`docs/releves.md`) : l'app
tournant désormais en permanence, elle surveille le dossier Téléchargements du PC. Un
relevé Swissquote ou Revolut, reconnu à son contenu et jamais à son nom, y est ramassé
dans la minute, ingéré et déplacé dans `inbox/` ; le reste du dossier n'est jamais
touché. Le tableau de bord rappelle une banque dont le relevé s'arrête depuis plus de
14 jours, avec le lien où le chercher. Aller le chercher chez la banque reste manuel :
pas d'API Swissquote pour les particuliers, et un agrégateur tiers lirait tout pour un
consentement à renouveler tous les trois à six mois.

**Fait les 16 et 17.10 — l'interface en React** (`docs/app-web.md`, `frontend/`) : à la
demande, pour une app plus belle et plus réactive, d'abord sur le téléphone. Flask garde
toute l'arithmétique et sert une API JSON par page (`web/api/`) ; React met en page et
dessine, à la largeur de l'écran. Les gabarits Jinja, `app.js`, `app.css` et
`web/charts.py` sont supprimés : la géométrie des graphiques vit dans
`frontend/src/charts/`, toujours en un seul exemplaire. Onglets en bas sur le téléphone,
période en feuille du bas, palette `Ctrl K`, reclassement depuis la fiche d'une
transaction avec annulation, tri des Twint par glissement. Les anciennes adresses
(`/reclasser`, `/day/…`) redirigent. Le build est versionné, et
`tests/test_frontend.py` échoue s'il ne correspond plus aux sources. Les tests de l'app
passent par l'API, et `test_browser.py` pilote l'app construite, au bureau et à 390 px
au doigt.

**Fait le 17.10 — l'assistant** (`docs/assistant.md`) : un modèle de langage au
choix (Claude, DeepSeek, ou Ollama en local), éteint tant que `data/ai.json` n'existe
pas. Il propose une catégorie aux commerçants qu'aucune règle ne reconnaît, résume la
revue du mois, explique pourquoi un mois a coûté plus, répond à une question en français
depuis la palette en renvoyant à la vue exacte, et traduit une phrase en scénario de
prévision. Il ne calcule rien : Flask lui donne les faits et rejette tout texte qui cite
un chiffre absent. Les noms de personnes partent masqués, tout envoi est noté dans
`data/ai_log.jsonl`. Le tri des Twint propose aussi une catégorie, sans modèle de
langage : un Bayes naïf appris sur les Twint déjà classés, qui affiche son taux de
réussite mesuré (`--twint-report`).

**Fait le 17.10 — tour complet de l'app** (toutes les pages, téléphone et bureau ;
aucune erreur ni débordement, aucune API lente) : le repère des revenus ne dessine plus
l'échelle d'un graphique par jour (le salaire d'un seul jour écrasait le mois) ; la
dépense moyenne par jour des faits marquants compte les deux bornes, comme la tuile
(les deux affichaient des moyennes différentes) ; « Premier bénéficiaire » ne répète plus la plus
grosse dépense ; besoins, envies, épargne en français partout (les clés restent Need,
Want, Save) ; le calendrier d'un mois prend la largeur au téléphone ; la palette se
rouvre vide ; « Pourquoi ce mois ? » sous le graphique des mois ; une journée allume
l'onglet Accueil.

**Fait le 17.10 — uv** : `run.bat` installe uv s'il manque, uv installe Python
(`.python-version`) et les dépendances aux versions exactes de `uv.lock`. Plus
d'installeur Python à lancer à la main ni de case « Add to PATH », et les mêmes
versions sur chaque PC : une réinstallation ne prend plus une version majeure sortie
entre-temps. Les `requirements*.txt` sont retirés, `uv.lock` fait foi.

**Fait le 18.10 — les filets de sécurité et l'assistant mesuré** :
- **la suite tourne sur GitHub** à chaque push (`.github/workflows/tests.yml`), navigateur
  compris, sans le relevé privé ;
- **une sauvegarde est relue**, pas seulement écrite (`backup.verify`), et l'app prévient
  quand une copie ne se relit pas ou que la dernière date de deux semaines ;
- **le premier lancement sans relevé** ouvre l'app sur l'import, au lieu de s'arrêter ;
- **le bouton « Mettre à jour »** fait le `git pull` et redémarre (`web/updates.py`) ;
- **le compte choisi** (`focus`) sur la page Épargne, à côté de la période, et « Zoom »
  retiré (l'axe ajusté était celui des montants) ;
- **ce que coûte l'assistant** (jetons, dollars, « au plus » pour DeepSeek) et **ce que
  valent ses catégories** (gardées, corrigées), page Assistant ;
- **l'épargne en mots** (« Expliquer la période ») et les questions sur les placements ;
- un seul format de fin de ligne (`.gitattributes`), l'assistant découpé en un module par
  usage, et des tests Vitest pour l'état dans l'URL.

**Fait le 19.10 — au-delà du relevé** : **À venir** (les engagements lus dans les
paiements, leurs dates, leurs hausses, le délai LAMal du 30.11, la franchise rejouée,
`docs/a-venir.md`) ; **Impôts** (chaque rubrique que le relevé renseigne avec la règle
fédérale, `docs/impots.md`) ; **Projets** (un voyage au coût net, les séjours proposés
avec la raison de chaque ligne, `docs/projets.md`) ; **le résumé de la semaine** poussé
par ntfy (`docs/semaine.md`) ; **contre la Suisse** dans l'Analyse (son inflation contre
l'IPC, son mois contre le ménage moyen) ; **l'indépendance financière** dans Prévisions ;
**le bilan de l'année** (`docs/bilan.md`) ; le change rejoué chez Revolut. En chemin : les
règles ne lisent plus l'adresse (le nom de rue d'un employeur faisait d'un salaire une
sortie culturelle), les virements entre ses propres comptes ne sont plus des revenus, et
la règle d'un assureur ne prend plus un autre assureur dont le nom contient le sien.

**Fait du 20 au 27.10 — devant, et la même mesure pour le plan** : UBS et camt.053
(`docs/releves.md`), les titres et biens hors relevé (`docs/impots.md`), le caviardage
d'un PDF (`docs/caviardage.md`) ; dans Prévisions, les ponctuels modifiables, les
versements limités à des mois de l'année, **le lissage des virements IBKR** au même point
bas, **le seuil d'alerte du cash** (rappelé partout et dans le résumé de la semaine),
**prévu contre réel** (`hindsight.py`) ; dans Impôts, **les impôts encore dus** estimés au
taux déjà payé et **les acomptes mensuels** (`docs/impots.md`) ; **le rappel 3a** de
novembre à décembre ; la médiane des colonnes, trimestre et semestre, la barre latérale
repliable, **le manuel** (`/aide`, `?`) ; la suite en parallèle (~1 min). En chemin, le
caviardage du vrai relevé était refusé (un nom accentué à un endroit, sans accent à un
autre ; le numéro de client loin de son libellé) : corrigé, avec un test par cas.

Un point ouvert : **une autre banque sans écrire de parser** (point 8). Entretien : la valeur du 3a lue dans l'app de temps en temps
(`--3a-value`), le jeton Flex à renouveler chaque année, et tous les deux ans le
plafond 3a (`fiscal.PILLAR3A_CEILING`). Le lecteur Flex lit le vrai relevé depuis le 08.10.

---

## 1. Format d'ingestion — vérifié le 08.08, rien d'autre que le PDF

**Vérifié le 31.07.2026 : pas de camt.053. Vérifié le 08.08 : pas d'export CSV ou
Excel non plus.** Le point est clos — ne pas reproposer la piste.

Conséquence : le PDF reste la voie d'ingestion, et ce n'est pas un problème — le parser
géométrique de `parser.py` rapproche chaque ligne du solde courant imprimé, sans le
moindre écart. Il est lent à écrire mais il est juste, et `reconcile()` le prouve à chaque
lancement. Le test de géométrie
(`test_columns_sit_in_their_documented_bands`) est la protection contre un changement de
mise en page.

## 2. Ledger multi-compte — fait pour Revolut le 05.10

`Ledger.merge()` refuse un IBAN différent — volontairement, pour ne pas mélanger deux
comptes par accident. Conséquence : les relevés finpension et Interactive Brokers ne
peuvent pas être ingérés.

Le panneau « Épargne » couvre déjà la vue consolidée (Swissquote + IBKR + 3a) par
snapshots : `data/ibkr.json` capturé via le connecteur IBKR MCP (recapturé le 02.10 —
NAV quotidienne du courtier sur l'année que couvre le connecteur), `data/finpension.json` régénéré par `--finpension` ou mis à
jour à la main depuis l'app finpension (lecture du 22.09). La mise à jour périodique
des snapshots est une routine de quelques minutes en session (skill `/epargne`), pas une feature manquante :
compléter `nav`/`nav_daily` d'IBKR, prolonger les `proxy_series` du 3a, et poser la
valeur lue dans l'app comme nouvelle observation (la précédente rejoint `yearly`, sinon
la courbe repart d'un point plus ancien). Le bouton ⟳ de l'app ne touche à aucun des
deux, et un nouveau journal finpension sans mouvement est identique à l'ancien.

**Le 05.10, Revolut est entré dans le ledger** comme compte secondaire (`account =
"revolut"`) : `merge()` garde l'IBAN du compte principal, chaque ligne porte son compte,
`gaps()` et `reconcile()` chaînent par (compte, devise). IBKR et le 3a restent des
snapshots, pour la raison qui suit.

Ce que le vrai ledger multi-compte apporterait en plus : le **journal de transactions**
IBKR (que le connecteur n'expose pas — il ne donne que des états) et l'ingestion des
relevés finpension. Tant que le journal n'est pas accessible, le gain est marginal :
ne pas l'entreprendre sans un changement d'usage (ou l'arrivée d'un export CSV chez
IBKR/finpension, ce qui rendrait chaque lecteur simple).

## 3. Règles perso éditables — fait le 08.08

`data/local_rules.json` s'édite depuis la page Corrections : section « Règles
personnelles » (liste, ajout, suppression, validation regex — un motif qui matcherait
tout est refusé), distincte des corrections manuelles. Le Store surveille le fichier :
une règle s'applique à la requête suivante, sans redémarrage.

## 4. Évolution des parts Need / Want / Save — fait le 22.09

Panneau « Évolution des parts Need / Want / Save » sous le bloc « Besoins, envies,
épargne », replié par défaut, ouvert par un lien du bloc ou par son titre. Deux bases
(`?shares=income|spending`), lissage `?smooth=1|3|6|12` en rapport de sommes
glissantes, mois bruts en pâle derrière la ligne lissée, axe borné à −100 / 200 % en
base revenus avec les mois hors cadre marqués au bord, repère 50/30/20. Le raisonnement
est dans `docs/app-web.md`.

Sur le ledger réel, lissé sur 6 mois, la lecture est nette : une part Need qui monte
durablement pendant que Save passe sous zéro se lit d'un coup d'œil, là où la série
brute sautait d'un bord à l'autre du cadre.

## 5. Revue du mois — fait le 22.09

Panneau « Revue du mois » sous les indicateurs, sur toute fenêtre d'un mois calendaire
(le mois en cours compris) : les prix fixes qui ont changé, les nouveaux bénéficiaires,
les débits peut-être doublés, les catégories au-dessus de leur habitude — chaque ligne
liée à ses transactions. Seuils nommés et justifiés dans `review.py`, raisonnement dans
`docs/review.md`. Calibrée sur le ledger réel : une médiane de deux signalements par
mois, dont une vraie hausse de prix d'un abonnement mobile.

## 6. Sauvegarde des décisions — fait le 08.10

Le ledger se reconstruit depuis les PDF ; ce que le titulaire a décidé, non. Les
corrections (`data/overrides.json`, des centaines au 22.09), les règles perso, les budgets et les
plans ne vivent que dans `data/`, gitignoré, sur un Bureau que OneDrive ne synchronise
pas (vérifié le 23.09). Un disque perdu, et ces heures de reclassement avec.

Fait : `python -m pms --backup [DOSSIER]` (`backup.py`) zippe `data/` et `inbox/` vers
`OneDrive/PMS-sauvegardes` par défaut, lancé par `run.bat` à chaque démarrage, en
gardant les dix dernières copies (`--keep`). Une copie n'est écrite que si le contenu a
changé depuis la précédente (empreinte des fichiers dans le commentaire du zip) : sinon
dix lancements identiques auraient chassé la copie utile. Un dossier de destination dans
le dépôt est refusé — ces fichiers ne doivent jamais y entrer, même privé. Restaurer :
dézipper à la racine.

## 7. Table de statistiques fiable — fait le 02.10

Mesurée le 02.10 contre la NAV quotidienne exacte d'IBKR, sur une année : la table
sous-estimait le rendement cumulé d'environ un quart, la volatilité d'environ 40 % et le
pire creux de moitié, et surestimait le Sharpe d'autant.

Causes : la série commence à la fin du premier mois, pas au début de la fenêtre (octobre
manque) ; des fins de mois seulement (11 rendements : la vol et les creux intra-mois
disparaissent) ; l'Ulcer index affiché comme un nombre alors que c'est une fraction ; des
taux annualisés sur des fenêtres de quelques mois ; une colonne 3a qui mesure ses indices
de référence, pas le compte ; une colonne totale diluée par le cash à 0 %, qui
flatte Sharpe et volatilité. Fait avec la refonte de la section : table quotidienne depuis le premier jour de la
fenêtre, colonne IBKR datée de son ouverture, 3a marqué « estimé », dilution du total
dite, Ulcer en %, chaque ligne définie en clair (`docs/epargne.md`). Sur la même année,
la table donne désormais les chiffres de la NAV quotidienne.
Depuis le 17.10, une fenêtre de moins d'un an se lit « sur la période » (volatilité et
ratios sur la durée de la fenêtre, rien de ramené à un an) ; l'annualisation reste
possible à la demande (`?stats=annual`), signalée comme extrapolée.

---

## 8. Une autre banque par recette — ouvert le 17.10

**Le besoin** : donner l'app à quelqu'un qui n'est ni chez Swissquote ni chez Revolut,
et qui ne code pas. Aujourd'hui, une banque de plus demande un parser écrit à la main
(README, « Brancher une autre banque ») : c'est le travail fait avec Claude Code pour
Revolut.

**L'approche retenue : le modèle écrit une recette, pas les transactions.** Le faire
transcrire tout le relevé a été écarté. Le relevé entier, avec IBAN, salaire et noms,
partirait chez le fournisseur, contre la règle des noms masqués (`docs/assistant.md`).
Sur des milliers de lignes, des lignes sautées ou inventées seraient probables, et chaque
nouvel export repasserait par le modèle. À la place :

1. un export qu'aucune banque de `banks.SOURCES` ne reconnaît est proposé à
   l'assistant : l'en-tête et une vingtaine de lignes, noms masqués ;
2. le modèle rend une **recette**, sans aucune donnée : séparateur, encodage, colonne
   et format de la date, montant (signé, ou débit et crédit), colonne de solde, colonnes
   du libellé, règles de `kind` vers le vocabulaire déjà connu (`CARD_KIND`,
   `PEER_KINDS`…) ;
3. l'app applique la recette elle-même, de façon déterministe, avec la même dérivation
   de référence que `revolut.py` (contenu de la ligne et rang dans la journée), puis lance
   `reconcile()`. Avec des soldes imprimés, une ligne mal lue casse la chaîne : c'est
   l'autotest qui rend l'approche sûre ;
4. l'utilisateur voit le résultat (nombre de lignes, période, soldes cohérents ou la
   première rupture) et valide d'un clic. La recette est enregistrée : les exports
   suivants de cette banque se lisent sans appel au modèle.

Une recette ne contient aucune donnée personnelle et peut donc être versionnée : écrite
une fois pour une banque, elle sert à tous ceux de cette banque, **sans clé d'IA**.
Elle ne doit recopier aucune valeur du relevé : la validation le vérifie.

**Fait le 18.10 — le camt.053** (`camt.py`, `docs/releves.md`) : le relevé ISO 20022
que la plupart des banques suisses exportent a son parser, écrit d'après la norme et son
schéma. Une banque qui le propose n'a plus besoin de recette ; il reste à le confronter au
premier vrai export d'un client. La recette reste utile pour les CSV et pour les banques
sans camt.053 (Neon, Yuh, les banques étrangères).

**Ordre** : CSV et xlsx d'abord (UBS, PostFinance, Raiffeisen, ZKB, BCV, Neon, Yuh en
proposent dans l'e-banking). PDF ensuite, avec des colonnes repérées par leur position
comme `parser.py`, plus fragile. Un export sans soldes ne se vérifie que par
« ouverture + mouvements = clôture », si ces soldes existent : l'app le dit.
Hors du point : une banque dont la devise principale n'est pas le CHF (chantier à part,
CLAUDE.md).

**Fichiers** : `banks.py` (une source « recette »), un `recipe.py` (appliquer, valider),
`assist/` (la demande), `/importer` (l'aperçu et la validation), `docs/releves.md`.

## Hors périmètre

Déclaré le 02.08.2026 : l'app ne sert **que sur laptop, en local**. Revu le 15.10,
quand l'usage a changé (le téléphone, par Tailscale) : le glisser-déposer au doigt et
le durcissement nécessaire à un accès par le tailnet sont faits (voir plus haut). Ce
qui reste écarté, et ne doit pas revenir sans un nouveau changement d'usage :

- **Exposition publique** (VPS, port ouvert, `tailscale funnel`) et la connexion
  applicative qu'elle exigerait (passkey ou mot de passe + TOTP, sessions, limite de
  tentatives). Tailscale réserve l'app aux appareils de l'utilisateur sans mettre les
  relevés chez un hébergeur ; tant qu'il suffit, l'app n'a pas de login.
- **Récupérer le relevé chez la banque sans l'utilisateur** : examiné le 15.10.
  Swissquote n'a pas d'API pour les particuliers ; un robot de connexion stockerait le
  mot de passe bancaire et contournerait la double authentification ; un agrégateur
  DSP2 (Revolut seulement) lirait toutes les transactions et redemanderait le
  consentement tous les 90 à 180 jours. (L'ingestion automatique, écartée le 02.08, est
  faite le 15.10 : voir plus haut.)

## Gardé pour plus tard

- **Un résumé poussé plutôt que consulté** (proposé le 15.10, mis de côté par
  l'utilisateur) : une fois par semaine, budgets dépassés, relevé en retard de N jours,
  épargne périmée, envoyé par ntfy (auto-hébergeable) ou par email. Les données existent
  déjà (`review.py`, `snapshots.py`) ; manque le canal.
