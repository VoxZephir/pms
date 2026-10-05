# Ce qui manque

État au 02.10.2026. L'app fait ce pour quoi elle a été construite : parser, réconcilier,
catégoriser, corriger à la main, naviguer dans le temps, en ressortir les données, prévoir
la trésorerie et le patrimoine (`/previsions`), analyser le passé mois par mois
(`/analyse`), suivre l'épargne hors relevé (Interactive Brokers, 3a) et comparer le coût
du change aux taux publiés. 535 tests, aucun écart de solde.

Ce qui suit est classé par ce que ça coûte de ne pas l'avoir, pas par difficulté.
Chaque point nomme le fichier concerné et une estimation d'effort en jours de travail
effectifs, pour être repris à froid.

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
227 corrections par nature, repliées, avec une recherche (17,9 → 2,3 écrans). Snapshots
d'épargne recapturés : IBKR, et 3a relevé dans l'app, tous deux au
22.09.

**Fait le 23.09** :

- **l'épargne ne vieillit plus en silence** : le panneau annonce toute poche dont les
  données s'arrêtent plus de 7 jours avant la date affichée ; la recapture est une skill
  (`/epargne`) et une commande (`--capture`, `--3a-value`) qui n'ajoutent que les points
  nouveaux et gardent la lecture 3a précédente — les deux erreurs de la mise à jour
  manuelle du 22.09 (`docs/epargne.md`) ;
- **les Twint se trient une touche chacun** : les 313 Twint sans bénéficiaire sont
  « Twint non identifié » plutôt que « Transferts P2P », et `/reclasser/tri` les
  présente un par un avec les mouvements du jour et les décisions passées au même
  montant, ou par montant récurrent d'un coup (`docs/corrections.md`). En chemin :
  l'envoi en place des formulaires perdait le bouton cliqué.

**Fait le 02.10 — le premier versement IBKR** : quelques milliers de CHF partis de Swissquote le 24.09
ont été lus comme de la performance (septembre IBKR à +34 % au lieu de +7.4 %, douze
mois à +77.6 % au lieu de +39.3 %, et la performance totale qui comptait le virement
comme un retrait). Les versements viennent désormais du ledger, le TWR les retire à la
convention d'IBKR, la table de statistiques aussi ; `/epargne` détecte un versement venu
d'ailleurs. Et la NAV IBKR est celle du courtier depuis le 01.10.2025 — la
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
(13.09.2023, pas août 2025 comme le connecteur le laissait croire) ; la valeur est
reconstruite chaque semaine jusqu'à la NAV quotidienne du courtier (+0.02 % d'écart au
raccord). La pire baisse IBKR sur tout l'historique est −29.2 % (avril 2025), pas
−8.85 %. Le retrait du 20.12.2024 revenu sur Swissquote n'est plus compté comme un revenu.

**Fait le 02.10 — repères et décomposition** : MSCI World (CHF) et SMI comparés à
chaque poche (bandeau, courbe en base 100, table de risque) ; la performance IBKR
décomposée entre le fonds en USD et le dollar contre le franc, le taux déduit de la
NAV du courtier (`docs/epargne.md`).

Reste à faire : **la sauvegarde de `data/`** (point 6).

---

## 1. Format d'ingestion — vérifié le 08.08, rien d'autre que le PDF

**Vérifié le 31.07.2026 : pas de camt.053. Vérifié le 08.08 : pas d'export CSV ou
Excel non plus.** Le point est clos — ne pas reproposer la piste.

Conséquence : le PDF reste la voie d'ingestion, et ce n'est pas un problème — le parser
géométrique de `parser.py` rapproche les 2187 lignes du solde courant imprimé, sans le
moindre écart. Il est lent à écrire mais il est juste, et `reconcile()` le prouve à chaque
lancement. Le test de géométrie
(`test_columns_sit_in_their_documented_bands`) est la protection contre un changement de
mise en page.

## 2. Ledger multi-compte — déprioritisé le 08.08, 3–5 j si un jour

`Ledger.merge()` refuse un IBAN différent — volontairement, pour ne pas mélanger deux
comptes par accident. Conséquence : les relevés finpension et Interactive Brokers ne
peuvent pas être ingérés.

Le panneau « Épargne » couvre déjà la vue consolidée (Swissquote + IBKR + 3a) par
snapshots : `data/ibkr.json` capturé via le connecteur IBKR MCP (recapturé le 02.10 —
NAV quotidienne du courtier depuis le 01.10.2025), `data/finpension.json` régénéré par `--finpension` ou mis à
jour à la main depuis l'app finpension (lecture du 22.09). La mise à jour périodique
des snapshots est une routine de quelques minutes en session (skill `/epargne`), pas une feature manquante :
compléter `nav`/`nav_daily` d'IBKR, prolonger les `proxy_series` du 3a, et poser la
valeur lue dans l'app comme nouvelle observation (la précédente rejoint `yearly`, sinon
la courbe repart d'un point plus ancien). Le bouton ⟳ de l'app ne touche à aucun des
deux, et un nouveau journal finpension sans mouvement est identique à l'ancien.

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

Sur le ledger réel, lissé sur 6 mois, la lecture est nette : Need autour de 50 % des
revenus jusqu'à fin 2025, puis jusqu'à 115 % au printemps 2026 pendant que Save passe
sous zéro — lisible d'un coup d'œil, là où la série brute sautait de −100 à 200 %.

## 5. Revue du mois — fait le 22.09

Panneau « Revue du mois » sous les indicateurs, sur toute fenêtre d'un mois calendaire
(le mois en cours compris) : les prix fixes qui ont changé, les nouveaux bénéficiaires,
les débits peut-être doublés, les catégories au-dessus de leur habitude — chaque ligne
liée à ses transactions. Seuils nommés et justifiés dans `review.py`, raisonnement dans
`docs/review.md`. Calibrée sur le ledger réel : une médiane de deux signalements par
mois, dont une vraie hausse d'opérateur mobile (27.90 → 28.90 CHF) en août 2026.

## 6. Sauvegarde des décisions — ouvert, ½ j

Le ledger se reconstruit depuis les PDF ; ce que le titulaire a décidé, non. Les
corrections (`data/overrides.json`, 227 au 22.09), les règles perso, les budgets et les
plans ne vivent que dans `data/`, gitignoré, sur un Bureau que OneDrive ne synchronise
pas (vérifié le 23.09). Un disque perdu, et ces heures de reclassement avec.

Proposé : `python -m pms --backup [DOSSIER]` qui zippe `data/` et `inbox/` vers un
dossier choisi (OneDrive, clé), lancé par `run.bat`, en gardant les N dernières copies.
Ne jamais pousser ces fichiers dans le dépôt, même privé.

## 7. Table de statistiques fiable — fait le 02.10

Mesurée le 02.10 contre la NAV quotidienne exacte d'IBKR, sur 01.10.2025 → 30.09.2026 :

| IBKR | Table | NAV quotidienne |
|---|---|---|
| Rendement cumulé | 30.75 % | 39.36 % (IBKR : 39.4 %) |
| Volatilité | 13.6 % | 21.9 % |
| Max drawdown | −4.2 % | −8.9 % |
| Sharpe | 2.46 | ~1.8 |

Causes : la série commence à la fin du premier mois, pas au début de la fenêtre (octobre
manque) ; des fins de mois seulement (11 rendements : la vol et les creux intra-mois
disparaissent) ; l'Ulcer index affiché comme un nombre alors que c'est une fraction ; des
taux annualisés sur des fenêtres de quelques mois ; une colonne 3a qui mesure ses indices
de référence, pas le compte ; une colonne totale diluée par des dizaines de milliers de CHF de cash à 0 %, qui
flatte Sharpe et volatilité. Fait avec la refonte de la section : table quotidienne depuis le premier jour de la
fenêtre, rien d'annualisé sous un an, colonne IBKR datée de son ouverture, 3a marqué
« estimé », dilution du total dite, Ulcer en %, chaque ligne définie en clair
(`docs/epargne.md`). Sur la même année, la table donne désormais 39.36 %, −8.85 %,
22.3 % — les chiffres de la NAV quotidienne.

---

## Hors périmètre

Déclaré le 02.08.2026 : l'app ne sert **que sur laptop, en local**. Trois chantiers ont
été écartés en conséquence, et ne doivent pas revenir sans un changement d'usage :

- **Glisser-déposer au doigt** : les événements tactiles ne servent à rien si l'app n'est
  jamais consultée sur téléphone. Le geste souris fonctionne.
- **Durcissement serveur** : le serveur de développement Flask sur 127.0.0.1 est la bonne
  exposition pour un usage strictement local. L'authentification ne devient nécessaire
  que le jour où le serveur est exposé sur un réseau.
- **Ingestion automatique (watcher)** : écartée le 02.08 — l'ingestion manuelle
  (`run.bat`) suffit. Ne pas reproposer sans un changement d'usage.
