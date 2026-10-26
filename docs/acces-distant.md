# Accès depuis le téléphone : Tailscale, gardes, gestes au doigt, import

<!-- Décidé le 15.10.2026, quand l'usage a changé : l'app ne servait que sur
     le laptop, elle doit aussi se lire sur le téléphone, n'importe où. Mis à
     jour le 17.10.2026 pour l'app React. -->

## Pourquoi pas un serveur loué

Un VPS aurait mis les relevés, le ledger et le jeton Flex d'IBKR sur une machine dont
l'hébergeur a le disque et la mémoire. Chiffrer le disque n'y change rien : la clé est
sur la même machine. Exposée sur internet, l'app aurait dû se défendre seule contre tout
le monde, avec une vraie connexion (passkey ou mot de passe + TOTP), des sessions, une
limite de tentatives — des jours de travail, puis l'entretien d'un serveur.

**Tailscale à la place.** Un VPN WireGuard entre les appareils de l'utilisateur. Le
serveur reste sur `127.0.0.1` ; `tailscale serve --bg 5000` met devant lui, sur le
tailnet seulement, un HTTPS avec un vrai certificat pour `pc.<tailnet>.ts.net`. Seuls
les appareils approuvés sur le compte Tailscale de l'utilisateur le joignent : c'est
l'authentification, et l'app n'en a pas d'autre. **Jamais `tailscale funnel`** : c'est
la variante publique, et elle remettrait l'app sans mot de passe sur internet.

Le prix : le laptop doit être allumé et en ligne. `python -m pms.web` demande donc à
Windows de ne pas se mettre en veille tant qu'il tourne, quand Tailscale est là
(`SetThreadExecutionState`, la demande que fait un lecteur vidéo : elle dure ce que dure
le processus, ne change aucun réglage, et ne s'oppose pas à un capot fermé).
`--allow-sleep` l'en dispense.

## Les trois gardes (`web/guard.py`)

L'app n'a pas de connexion. Sur 127.0.0.1 ça suffisait ; joignable depuis un téléphone,
trois contrôles tiennent la porte :

- **L'en-tête Host doit nommer cette machine** (`TRUSTED_HOSTS` de Flask 3.1) :
  `localhost`, `127.0.0.1`, et tout `*.ts.net`. Sans ça, une page web qui fait pointer
  son propre domaine sur 127.0.0.1 (DNS rebinding) lit chaque réponse comme si c'était la
  sienne. Le suffixe `.ts.net` entier est sûr : le DNS de Tailscale ne résout jamais un
  de ces noms vers 127.0.0.1. Il laisse passer le téléphone même quand le nom n'a pas pu
  être lu au démarrage. IPv6 (`[::1]`) ne passe pas le contrôle de Werkzeug — sans
  conséquence, le serveur n'écoute qu'en IPv4.
- **Une écriture doit venir d'une page de l'app, par son Origin.** Pas de cookie de
  session à voler, donc l'attaque possible est une page d'un autre site qui POSTe vers
  `/api/refresh` ou `/api/budgets`. L'Origin (ou, à défaut, le Referer) doit valoir
  l'hôte de la requête, le nom Tailscale lu au démarrage, ou le `X-Forwarded-Host` posé
  par `tailscale serve` — un navigateur ne peut pas forger cet en-tête d'un site à
  l'autre sans un preflight que l'app n'accorde jamais. Le port compte : une autre app
  sur `localhost:3000` est un autre site. `null` (cadre sandboxé, referrer supprimé) est
  refusé. Une requête sans Origin ni Referer n'est pas un navigateur (le client de test,
  curl) : elle passe, aucune requête intersite n'arrive sans l'un des deux. Refus : 403,
  en JSON, qui dit d'où venait la requête.
- **Le serveur n'écoute que sur loopback ou le tailnet** (`bind_problem`, vérifié avant
  de construire l'app). `0.0.0.0` ou une adresse du réseau local exposeraient une app
  sans mot de passe au Wi-Fi du moment. `--debug` n'est accepté que sur loopback : la
  console de Werkzeug exécute du Python pour qui l'atteint.

Le nom Tailscale est lu par `tailscale status --json` (`guard.tailnet_name`), avec un
délai de 4 s et aucune exception qui remonte : son absence ne doit jamais empêcher le
serveur de démarrer. Il sert à la bannière (l'adresse à ouvrir sur le téléphone), aux
origines admises et à la veille.

## Le téléphone

L'app React (16–17.10) est pensée d'abord pour lui ; le détail est dans
`docs/app-web.md` (« Sur le téléphone », « Gestes »). L'essentiel :

- **onglets en bas**, là où est le pouce, et la période dans une barre collée en haut,
  qui ouvre une feuille du bas ;
- **les graphiques sont dessinés à la largeur de l'écran**, au lieu des 720 px fixes
  qu'on faisait défiler de côté ; le glissement vertical reste à la page ;
- **au doigt**, un premier toucher montre les chiffres d'une colonne, un second
  l'ouvre ; un glissement de côté sélectionne une plage ou lit la courbe point par point ;
- **reclasser** se fait depuis la fiche d'une transaction (un toucher sur la ligne) ou en
  sélection multiple, jamais par un glisser-déposer qu'un doigt ne démarre pas ;
- `theme-color` suit le fond de la page et le thème choisi ; `viewport-fit=cover` et
  `env(safe-area-inset-*)` écartent encoche et barre de gestes ;
- les champs sont à 16 px, sinon iOS zoome ; les cibles font au moins 44 px.

`test_browser.py` pilote chaque page à 390 px, écran tactile : aucune ne défile de côté,
les onglets et la feuille de période marchent, et le double toucher sur une colonne
aussi.

**Écran d'accueil.** `static/manifest.webmanifest`, des icônes PNG 180 (iOS, qui n'en
lit pas d'autre et arrondit lui-même les coins : tuile carrée), 192, 512 et 512
« maskable » (glyphe dans le cercle de sécurité), toutes dessinées comme le favicon.
`display: minimal-ui` et non `standalone` : l'app s'appuie sur l'historique du
navigateur, et un mode autonome sur iPhone n'a pas de bouton retour. Pas de service
worker hors ligne : il garderait des données financières en cache sur le téléphone.

**Gzip (`web/compress.py`)** (15.10). Le serveur répond en 10 à 200 ms ; sur le
téléphone, ce qu'un clic attend, c'est le transfert. Une douzaine de lignes plutôt que
flask-compress. Seul le texte est compressé : PNG, polices et xlsx (un zip) le sont
déjà. Un fichier statique compressé garde son ETag en version faible, ce qui laisse la
visite suivante se revalider en 304. Avec l'app React, le premier chargement coûte
244 Ko de JS et CSS compressés plus la police, une fois par build (assets immuables) ;
une vue coûte ensuite son JSON, 4,6 Ko pour le mois en cours. BREACH (lire un secret par
la taille des réponses compressées) n'a rien à lire ici : aucune réponse ne porte de
jeton, la garde passe par l'Origin.

**React, finalement** (16.10). Une première fois écartée le 15.10 : le design venait
du CSS, et calculer dans le navigateur aurait doublé l'arithmétique. Refaite à la
demande de l'utilisateur, sans ce défaut : l'arithmétique reste entièrement en Python et
arrive en JSON. Seule la géométrie des graphiques est passée dans le navigateur, et elle
n'a toujours qu'une implémentation (`frontend/src/charts/`, `charts.py` supprimé).

## Importer un relevé depuis le téléphone (`/importer`)

L'export CSV de Revolut naît sur le téléphone ; le PDF Swissquote s'y télécharge aussi.
La page `/importer` (dans la barre latérale, ou « Plus » sur le téléphone) envoie le
fichier à `/api/import` en multipart, choisi ou déposé ; un relevé de deux ans se lit en
~15 s.

- **Où il va** : `banks.placement` choisit le dossier que lit la banque de cette
  extension (première source de `banks.SOURCES` qui la prend), donc là où `parser_for`
  le cherchera. Le nom est celui de l'envoi, réduit à des caractères sans histoire
  (accents retirés, jamais de chemin), et ne remplace jamais un autre fichier
  (`-2`, `-3`…). Le même contenu déjà présent n'est pas réécrit.
- **Refusé avant le disque** : une extension qu'aucune banque ne lit, un `.pdf` qui n'en
  est pas un, un `.csv` binaire, plus de 25 Mo (`MAX_UPLOAD_BYTES`). La réponse dit
  pourquoi, en JSON.
- **Ingéré tout de suite**, ce qui veut dire : intégré au ledger, ou renvoyé avec la
  raison. Un fichier qu'aucun parser ne lit, ou dont il ne tire aucun mouvement, est
  retiré d'`inbox/` — laissé là, il ferait échouer chaque lancement suivant.
- **Un verrou** (`intake.LOCK`) sérialise l'import, « Relire les relevés » et la
  surveillance des Téléchargements : deux ingestions simultanées enregistreraient chacune
  le ledger qu'elles ont lu, et la seconde perdrait les lignes de la première. Le chemin
  commun (`intake.take`) et la surveillance : `docs/releves.md`.
- La page liste les derniers imports et ce que la surveillance des Téléchargements a
  fait (`/api/imports`).

## Ce qui reste hors périmètre

L'exposition publique (VPS, port ouvert, `tailscale funnel`) et donc la connexion
applicative qu'elle exigerait : écartées tant que Tailscale suffit.

Mis en service le 15.10 sur le laptop et un téléphone Android (navigateur Chromium). Deux leçons : le nom
`.ts.net` se résout aussi par le DNS public, donc un DNS filtrant (AdGuard) n'empêche
rien — les premiers « site inaccessible » venaient très probablement de l'émission du
certificat HTTPS à la première requête ; et une écriture depuis le téléphone (reclasser,
annuler) passe la garde d'Origin derrière `tailscale serve`.
