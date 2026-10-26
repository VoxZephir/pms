# L'assistant : un modèle de langage, tenu court

<!-- Lu à la demande, quand on travaille sur `ai.py`, `assist/`, `twint.py`,
     `web/api/assist/` ou `frontend/src/components/assist/` (voir « Où
     lire avant de toucher » dans CLAUDE.md). -->

La règle de l'app vaut aussi pour lui : **Flask calcule, le modèle met en mots**. Il lit
des chiffres que l'app a déjà calculés, ou il traduit une phrase en une requête que l'app
exécute elle-même. Il n'additionne rien, n'écrit rien sans un clic, et chaque chiffre qu'il
écrit est confronté aux chiffres qu'on lui a donnés.

## Ce qu'il fait

| Où | Quoi | Ce qui part chez le fournisseur |
|---|---|---|
| Palette Ctrl K, « Demander : … » | une question en français → une requête (`assist.plan_question`) → l'app calcule (`run_query`) → deux phrases, et le lien vers la vue exacte | la question, les catégories, puis les résultats calculés (totaux, bénéficiaires) |
| Corrections, « Bénéficiaires non classés » | une catégorie proposée pour chaque commerçant qu'aucune règle ne reconnaît ; « Accepter » pose la règle (`/api/reclassify`, annulable) | nom du commerçant, lieu, nombre de passages, montant médian |
| Tableau de bord, revue du mois | « Résumer en trois phrases » : la revue (`review.month_review`) en prose | les listes de la revue, rien d'autre |
| Tableau de bord, revue du mois | « Pourquoi ce mois ? » : l'écart à la médiane, ponctuel ou habitude, et les lignes qui le portent | écarts par catégorie, les huit plus grosses lignes du mois |
| Prévisions, « Scénario en mots » | une phrase → des lignes du plan (versement, ponctuel, revenu, dépense), projetées à côté du plan actuel, enregistrées comme scénario nommé | la phrase, les déclarations du plan (pas de transaction) |

**Les Twint muets ne passent pas par lui.** Leurs suggestions viennent d'un modèle
statistique local, appris sur les Twint déjà classés à la main (plus bas).

## Ce qui rend une réponse informative (18.10)

La première version, à l'usage, répondait juste mais disait peu : une question ne
recevait qu'un total, le résumé du mois que les quatre listes de la revue (souvent vides,
donc « rien d'inhabituel »). Le modèle ne peut pas être plus riche que ce qu'on lui
donne, et il n'a pas le droit de calculer. D'où :

- **`period_facts`**, un tableau complet d'une période, calculé par Flask : total,
  lignes, par jour ; la même durée juste avant et la même période un an avant (écart en
  francs et en %) ; les catégories avec leur part et leur écart à la période d'avant ;
  les plus gros changements ; les bénéficiaires ; les plus grosses lignes ; revenus, net
  et taux d'épargne ; mois par mois au-delà de 45 jours. Chaque écart et chaque
  pourcentage y est déjà calculé : le modèle choisit et dit, il n'additionne pas.
- **Des questions de plusieurs sortes** (`assist.FOCUS`) : total, catégories,
  bénéficiaires, grosses lignes, mois par mois, épargne, jours de la semaine,
  abonnements, deux périodes comparées, **le solde** à une date, et **l'avenir** : la
  projection de la page Prévisions (`plans.project`), avec un seuil (« et si je ne veux
  jamais descendre sous 10k ? ») dont le franchissement est calculé par l'app. La
  première version répondait à cette question que l'app ne faisait pas de prévision :
  elle en fait, la question ne le savait pas.
- **Un tableau sous chaque réponse**, construit par l'app (`run_query` renvoie
  `table`) : des barres quand il y a un montant par ligne, un tableau sinon. Les chiffres
  de la phrase sont mis en gras (`Figures`). La réponse dit l'essentiel, le tableau porte
  le détail : le modèle n'a pas à tout énumérer.
- **Une conversation** : la palette garde les échanges, propose deux ou trois questions
  de suivi (chips), et le planificateur reçoit les deux derniers échanges, pour que « et
  l'année d'avant ? » veuille dire quelque chose. Quatre questions d'exemple ouvrent la
  palette quand le champ est vide.
- **Le bilan du mois** remplace le résumé en trois phrases : un titre et trois à cinq
  constats chiffrés, nourris par la revue *et* par le mois face à la médiane de chaque
  catégorie, les revenus et l'épargne face à l'habitude, l'année depuis janvier face à
  l'an passé. Sous le texte, les catégories les plus éloignées de leur médiane en barres
  (hausse en rouge, baisse en vert). « Pourquoi ce mois » montre le mois parmi les
  douze précédents, face à leur médiane (`Columns`). « Réécrire » redemande sans cache.
- **Une seconde chance au lieu d'un rejet sec** (`_ask_checked`) : un chiffre absent des
  faits, presque toujours un calcul du modèle, lui est renvoyé (« ta réponse citait X,
  absent des données ») pour une réécriture ; une seconde erreur écarte la réponse.

**La recherche web**, pour un commerçant inconnu (« Atelier Nordwind ») : seule l'API de
Claude cherche elle-même (`web_search_20260209`, cinq recherches au plus par requête ;
la forme JSON est alors demandée en mots et vérifiée par `validate`, et un tour mis en
pause par une recherche longue est relancé). DeepSeek et Ollama ne cherchent pas. Pour
tous, chaque bénéficiaire non classé porte un lien « Chercher sur le web » : c'est le
navigateur du titulaire qui cherche, l'app n'envoie rien. Ce qui part en recherche est un
nom de commerce et sa ville, jamais un nom de personne (ceux-là ne sont pas envoyés du
tout).

**Fidèle aux maquettes du 17.10** (la page « PMS, pistes IA ») : chaque carte de
l'assistant a un titre et son badge (réponse, résumé, explication, suggestions, à
valider), ses chiffres soulignés en pointillé avec leur provenance au survol, et des
pastilles « d'où viennent ces chiffres ». La question porte le lien de sa vue et se range
dans les questions récentes de la palette (ce navigateur seulement). Le bilan se raccourcit
ou se masque (préférence locale), « Ce qui a changé » montre les écarts en barres,
« Pourquoi ce mois » titre l'écart (« Juin, +120 sur la médiane ») et sépare les
lignes ponctuelles des catégories qui dérivent. Le scénario se lit comme un diff (la ligne
ajoutée en vert, puis début, durée, rendement), sur la courbe du patrimoine quand les
poches sont connues, avec l'écart à l'horizon, « Enregistrer » et « Modifier ». Une
suggestion de catégorie porte la teinte de la catégorie et la règle qui sera posée.

**« Combien puis-je épargner sans passer sous X ? »** se calcule (`forecast_facts`) :
le montant constant, chaque mois dès maintenant, qui garde toutes les fins de mois
au-dessus du seuil (le mois le plus serré décide), arrondi à la dizaine du côté prudent ;
négatif, c'est ce qu'il faut retirer de l'épargne ou des dépenses. Les versements vers le
3a ou le placement sont séparés des dépenses ponctuelles : la première version les
mélangeait, et la réponse ignorait les versements mensuels déjà programmés.

**Un plancher de cash dans « Scénario en mots »** (« et si je ne veux pas descendre sous
10k ? ») n'est pas une ligne du plan : le modèle le reconnaît (`floor`) sans rien
proposer, et l'app calcule ce qui le tient (`_floor_changes`, sur `forecast_facts`).
Avec de la marge : ce montant de plus versé chaque mois au placement. Avec un manque : le
plus gros versement mensuel baisse d'autant, puis la dépense mensuelle pour le reste ; si
même tout cela ne suffit pas, l'app le dit au lieu de proposer une dépense nulle. **Le
montant se cherche sur la projection elle-même**, changements appliqués, par dichotomie à
la dizaine de francs : la première version le tirait d'une formule qui supposait le
changement appliqué dès ce mois-ci, et sur le vrai plan, où le versement ne commence
qu'en janvier, le scénario proposé finissait plus d'un millier de francs sous le plancher. Le graphique
montre alors le cash (le patrimoine ne bouge presque pas : l'argent passe d'une poche à
l'autre), avec la ligne du plancher ; une bascule montre le patrimoine. Le
scénario se montre et s'enregistre comme les autres, la ligne retirée en rouge.

**Ce qui varie se choisit, et chaque option est chiffrée d'avance.** Sur un manque, la
réponse dit d'abord où le plan casse : « le cash descend à 8'850 en août, 1'150
sous ton plancher ». Elle liste ensuite chaque façon de tenir le plancher avec un seul
levier, sous forme de phrase concrète :

- « Verser 400 au lieu de 500 chaque mois au placement » ;
- « Dépenser 3'880 au lieu de 4'000 par mois » ;
- « « Voyage » : 2'850 au lieu de 4'000 » ;
- « Renoncer à … », quand il faut aller jusqu'à zéro.

Une option est cochée, la première qui suffit, et la courbe la montre. Les leviers qui ne
suffiraient pas seuls, même ramenés à zéro, sont nommés sur une ligne. « Les deux »
(le plus gros versement, puis la dépense) n'apparaît que si aucun levier ne suffit seul.

La première version proposait les leviers comme des puces nues, quatorze avec les
ponctuels, et ne chiffrait que celle qu'on cliquait. On lisait un mur de boutons, puis un
diff « − 500 / + 400 » suivi du rendement et de la durée du versement. Chiffrer toutes
les options d'un coup coûte peu : le cash bouge en proportion de la coupe. La courbe à
l'extrémité dit donc où chaque franc atterrit, et l'estimation est vérifiée puis ajustée
à la dizaine sur la projection (`solve`, avec la dichotomie en secours). Cela fait
quelques projections par levier au lieu d'une douzaine. Cocher une autre option ne
rappelle pas le modèle : la phrase revient du cache.

Un bénéficiaire resté sans suggestion se **redemande** (bouton sur sa ligne), en
passant les caches : une première demande faite sans recherche web restait sinon figée
sur « pas de suggestion ».
Le bénéficiaire redemandé passe en tête du lot : seuls les premiers de chaque lot sont
cherchés. La réponse dit ce que la recherche a rapporté, avec les pages trouvées :
« la recherche web a rendu 3 pages, sans permettre de conclure ». Sinon, une réponse
toujours vide s'affichait exactement comme avant, et le bouton semblait ne rien faire.
Le journal de la page Assistant donne l'issue de chaque recherche : le nombre de pages,
« échec HTTP 4xx », « injoignable », ou « aucun résultat lisible » avec les clés reçues.
C'est ce qui permet de voir une recherche qui échoue sans bruit.

**Ce qui est cherché** (`assist.search_query`) : le nom exact entre guillemets, puis la
ville. Sans guillemets ni ville, le nom d'un petit commerce trouvait un footballeur au
nom voisin. Un paiement sans lieu imprimé (l'export Revolut n'en a pas) prend comme
**lieu probable** la ville où la carte a servi ce jour-là ou la veille, ou le lendemain
(`_probable_town`). C'est une piste pour la recherche et pour le modèle, pas un fait :
la ligne l'écrit « carte utilisée à … ce jour-là ». Si les guillemets ne trouvent rien,
une seconde recherche est faite sans eux.

**La recherche web de DeepSeek** (`ai.search_snippets`, `POST /v1/tools/search`, la même
clé) nourrit la proposition de catégories : jusqu'à 15 commerçants par lot, nom et
ville, trois résultats chacun, passés au modèle sous « recherche_web ». Sa documentation
n'était pas lisible depuis la session qui l'a écrit (hôte bloqué) : seuls l'adresse,
l'authentification et les champs `query` et `count` sont connus. La réponse est donc lue
avec tolérance (`results`, `data` ou `items` ; titre, URL, texte), et un échec n'est
qu'une absence de résultat. Chaque recherche est dans le journal ; facturée à partir du
1er novembre 2026 (0.75 $ les 1'000 appels, selon une source secondaire).

## Les garde-fous, et pourquoi chacun

- **Un schéma JSON par tâche** (`ai.strict`, `ai.validate`). Claude le reçoit comme
  sortie structurée ; DeepSeek et Ollama n'offrent qu'un « mode JSON » qui garantit du
  JSON, pas la forme : le schéma est donc dans les instructions, et `validate` vérifie
  la réponse dans tous les cas. Une réponse hors format est rejetée, pas réparée.
- **Chaque chiffre écrit doit venir des faits** (`ai.unsupported_numbers`). Les nombres
  du texte (format suisse compris, 1'234.50) sont comparés à ceux des faits, arrondis au
  centime, au franc, à la dizaine et à la centaine. Un jour du mois, une année, un petit
  compte passent. Un chiffre inventé fait écarter le texte entier, avec la raison : un
  total « calculé » par le modèle finirait par contredire celui de l'app.
- **Ce que le modèle choisit, l'app le valide.** Une catégorie hors de la liste du
  titulaire devient « pas de suggestion ». Une période hors du relevé est bornée. Les
  lignes citées dans « Pourquoi ce mois » sont des index dans la liste envoyée. Un
  scénario passe par `apply_plan_action`, le même chemin que le formulaire : ce que le
  plan refuserait (une poche absente, un montant négatif) n'est pas montré.
- **Rien ne s'écrit sans un clic.** Une suggestion de catégorie attend « Accepter ». Un
  scénario est montré avant d'être enregistré, et même enregistré il n'est pas rendu
  actif : il apparaît dans la comparaison, et basculer dessus reste le geste de
  l'utilisateur. Chaque écriture s'annule depuis le toast.
- **Un GET ne coûte rien.** Les pages lisent ce qui a déjà été demandé
  (`ai.memo_get`, dans `data/ai_cache.json`) ; seul un bouton appelle le modèle. La
  revue d'un mois est rangée sous l'empreinte de ses faits : un nouvel import qui
  change la revue redemande, un rechargement de page non.

## Ce qui quitte la machine

- **Les noms qui ne sont pas du commerce partent masqués.** Une carte nomme un
  magasin, un virement nomme une personne, une régie, un employeur : la même frontière
  que `data/local_rules.json`. `ai.Redactor` remplace ces noms par `[P1]`, `[P2]`…
  avant l'envoi, et les remet dans la réponse. Le panneau des bénéficiaires n'envoie
  même pas les noms de personnes : il les compte (« restent hors de la liste »).
- **Jamais l'IBAN, le numéro de client, le nom du titulaire, ni une transaction
  entière.** Seulement les champs listés dans le tableau du haut.
- **Tout est noté** dans `data/ai_log.jsonl`, tel qu'envoyé : la date, la tâche, le
  fournisseur, le texte. C'est la réponse à « qu'est-ce qui est parti ? ».

## Les fournisseurs

**Le choix se fait dans l'app**, page Assistant (`/assistant`, `pages/Assistant.tsx`) :
éteint, ou un fournisseur et un modèle, avec un bouton « Tester » (une requête de
quelques mots, jamais mise en cache) et le journal des derniers envois. Le choix est écrit
dans `data/ai.json` (`ai.save_config`). **La clé, elle, reste un fichier** :
`data/ai.<fournisseur>.key` (`ai.anthropic.key`, `ai.deepseek.key`), une par
fournisseur, pour passer de l'un à l'autre sans rien éditer ; un `data/ai.key` unique
sert à défaut. Comme le jeton Flex, une clé n'est jamais imprimée, jamais mise dans un
message d'erreur, jamais envoyée au navigateur, jamais demandée : la page dit seulement
si elle est posée, et dans quel fichier la mettre. Une page sans connexion qui
accepterait une clé collée serait un formulaire de plus à garder. Éteint, l'app tourne
comme avant et les boutons de l'assistant n'apparaissent pas.

| `provider` | Comment | À savoir |
|---|---|---|
| `anthropic` (défaut) | SDK `anthropic`, sortie structurée, `effort` bas par défaut, repli serveur en cas de refus (`fallbacks: "default"`) | modèle par défaut `claude-opus-5-5` ; `claude-haiku-5-5` coûte bien moins pour ces tâches courtes, au choix de l'utilisateur dans `ai.json`. L'API n'entraîne pas ses modèles sur ces données. |
| `deepseek` | format OpenAI sur HTTP (`urllib`, aucune dépendance) | bon marché. Selon sa politique de confidentialité, l'entreprise stocke les données en Chine, sous le droit chinois : c'est la question à trancher avant de lui envoyer des montants, même masqués. |
| `ollama` | le même format, sur `127.0.0.1:11434` | rien ne sort du PC. Un 7B sur le CPU du laptop met des dizaines de secondes, et suit moins bien le schéma : assez pour les résumés et les catégories, plus fragile pour la question et le scénario. |

Un autre service au format OpenAI se branche avec `"provider": "deepseek"` et un
`"base_url"` à lui.

## Les Twint muets : des suggestions apprises du titulaire

« Paiement Twint » et rien d'autre : aucune règle ne lit une catégorie sur cette ligne,
et aucun modèle de langage non plus. Ce qui existe, ce sont les centaines de Twint déjà
classés à la main, et autour de chacun le reste du relevé ce jour-là. Les petits
montants un soir de week-end remboursent un verre à un ami ; quelques centaines de
francs après un séjour à l'étranger sont une part de voyage. C'est une régularité des
décisions du titulaire, et elle se mesure.

`twint.py` est un petit Bayes naïf sur ce que le relevé imprime vraiment : la tranche
de montant, le montant exact, s'il est rond, le jour de la semaine, les catégories
payées par carte le même jour, un séjour à l'étranger à ±1 jour (« pendant ») ou dans
les 45 jours avant (« après »), le même montant à un mois d'écart.

**Un séjour à l'étranger, ce sont des magasins sur plusieurs jours.** La première
version comptait tout paiement par carte dont le lieu n'est pas la Suisse : sur le
relevé réel, presque tous les Twint tombaient « près d'un voyage », parce qu'un service en
ligne facturé depuis l'Irlande ou les Pays-Bas revient chaque mois. La deuxième écartait
les sites (un commerçant étranger payé sur trois mois ou plus) mais gardait une fenêtre
de 45 jours après chacun des jours retenus : plus de la moitié des restaurants restaient
« près d'un voyage ». Un séjour est désormais une suite de jours d'achats en magasin à
l'étranger, à deux jours d'écart au plus, sur deux jours ou plus et chez deux
commerçants ou plus : une journée de courses de l'autre côté de la frontière n'en est
pas un. « Pendant » va de trois jours avant le départ au lendemain du retour, « après »
couvre les deux semaines qui suivent.

**La convention du titulaire pour les parts de voyage (17.10).** Un Twint qui rembourse
une part de quelque chose se classe selon ce que l'argent a payé : une part de voyage
remboursée à une amie est un voyage (« Loisirs & voyages »), pas un transfert à une
personne. Sinon l'analyse sous-estime ce que coûtent les voyages, et compte en
« Transferts P2P » ce qui n'en est pas un. Sur la carte du tri, un Twint de 100 CHF ou
plus pendant un séjour ou dans les deux semaines qui suivent rappelle le séjour (dates,
pays) et met « Loisirs & voyages » en avant (`twint.trip_hint`). C'est un rappel, pas
une décision : le titulaire sait si c'était le voyage ou autre chose.
Il apprend sur les Twint épinglés par le titulaire, puis il est **mesuré sur eux,
tranche de montant par tranche** : chaque Twint est retiré de l'apprentissage puis
prédit (validation croisée « un contre tous »). Un seul taux global ne disait rien :
sur le relevé réel, presque tous les Twint classés sous 60 CHF étaient « Restaurants &
bars », et les rares au-dessus de 120 CHF une demi-douzaine de catégories différentes. Le
taux global, flatteur, valait
exactement « répondre toujours Restaurants », et masquait que la suggestion est sûre en
bas et sans valeur en haut.

La carte du tri ne montre donc une suggestion que dans une tranche où elle a été
mesurée juste (au moins 10 cas, au moins 80 %), avec :

- la suggestion et sa probabilité, puis les deux suivantes ;
- les indices qui la portent le plus (« un week-end · montant de 5 à 15 CHF ») ;
- le taux de cette tranche : « mesuré sur tes N Twint de 15 à 30 CHF déjà classés ».

Une tranche mélangée peut quand même contenir des cas sûrs. Sur le relevé réel, une
tranche intermédiaire n'était qu'aux trois quarts « Restaurants & bars », sous la barre. Les suggestions que le modèle
y donne à 90 % de confiance ou plus sont donc mesurées à part, avec la même validation
croisée. Si, à ce niveau de confiance, elles ont été justes 80 % du temps sur au moins
10 cas, une suggestion aussi sûre s'affiche, avec ce taux-là (« où il était aussi
sûr »). Les autres Twint de la tranche restent sans suggestion.

Et dans une tranche presque toute d'une catégorie (au moins 90 % sur au moins 10 cas),
le tri propose le reste de la tranche en une décision (« N Twint de 15 à 30 CHF →
Tout en Restaurants & bars »), annulable depuis le toast comme les montants récurrents.
Au-dessus, rien n'est proposé : ces Twint-là se classent un par un, avec la mémoire du
titulaire. Il ne pré-sélectionne rien et n'applique rien : le bouton mis en avant
est sa première idée, la décision reste un toucher. Chaque épingle recharge le ledger,
donc la carte suivante apprend déjà de la dernière.

`python -m pms --twint-report` imprime l'analyse derrière : par catégorie le montant
médian, la part le week-end et près d'un voyage ; par tranche de montant les catégories
choisies ; et les taux de la validation croisée. Ce ne sont que des agrégats, sans
ligne ni date : on peut le coller dans une conversation pour régler les indices.

## Ce que ça coûte, ce que ça vaut (page Assistant)

**Le coût vient des jetons que renvoie le fournisseur**, enregistrés avec chaque requête
dans `data/ai_log.jsonl` (`usage` : envoyés, lus depuis le cache du fournisseur, reçus,
recherches web) : `usage` de l'API Anthropic, `usage` du format chat de DeepSeek et
d'Ollama. Une requête échouée est journalisée aussi (`outcome: échec`), car elle a pu
être facturée. Le prix vient de `ai.PRICES`, tarifs publics d'octobre 2026 en dollars par
million de jetons. **DeepSeek facture le double aux heures pleines**, et l'app ne sait pas
lesquelles s'appliquaient : elle compte au tarif plein et écrit « ≤ ». Un modèle absent de
la table est compté en jetons, pas en dollars ; Ollama coûte zéro. La page montre le mois
en cours et le précédent (`ai.spending`). Les requêtes d'avant le comptage sont dites
« non chiffrées ».

**Ce que valent les catégories proposées aux commerçants se lit dans le ledger**, pas dans
les clics (`api/assist/settings._merchant_outcomes`) : un bénéficiaire dont les lignes sont
aujourd'hui dans la catégorie proposée est « gardé tel quel » ; dans une autre, « corrigé »
(trois exemples nommés) ; encore « Non catégorisé », « en attente ». C'est la même
honnêteté que le taux mesuré du tri des Twint : dire si l'assistant sert, plutôt que le
supposer.

## L'épargne en mots, et les questions sur les placements

**« Expliquer la période »**, sur la page Épargne sous le bandeau
(`/api/ai/savings`, `assist.explain_savings`) : deux ou trois phrases sur ce qui a fait
bouger l'épargne. Elles disent la part des versements, celle des marchés, et la poche qui a
porté le résultat. Les faits sont ceux de la table « Par poche » (`SavingsBook.summary`,
via `api/savings.pocket_summaries`), pour la fenêtre et le compte choisis :
valeur au début et à la fin, versé, gain de marché, TWR et MWR. Comme ailleurs, un chiffre
absent de ces faits fait rejeter la réponse après une seconde chance. Aucun conseil
d'investissement ni prévision n'est demandé. La réponse est gardée sous l'empreinte des
faits : elle se relit sans nouvel appel tant que les chiffres ne bougent pas.

**La palette répond aussi sur les placements** (`focus` « placements ») : « combien ont
rapporté mes placements cette année ? » reçoit les mêmes faits et, sous la réponse, la table
par poche (valeur, versé, gain, TWR). Le lien de la réponse mène à la page Épargne sur la
même fenêtre. `assist/` ne lit pas la couche web : la route lui passe les résumés par
une fonction (`run_query(..., savings=)`).

## Une hypothèse de marché en mots (`/api/ai/rates`)

Dans « Rendement et volatilité supposés », une phrase (« un krach de 30 % l'an prochain
puis 6 % par an, vol 18 %, sur 10 ans ») devient un barème : des périodes de rendement
annuel, une volatilité si la phrase parle de risque (sinon celle du plan reste), un
horizon si elle donne une durée. Le modèle lit la phrase ; il ne calcule rien de ce qui
s'affiche. Le serveur borne sa réponse comme le formulaire (1 à 480 mois, −60 à +40 % par
an, volatilité 0 à 100 %, refus sinon) et dessine ce que le barème fait à 1'000 CHF avec
`plans.growth_path`, à côté de ce que fait le barème actuel sur la même durée. La réponse
dit d'où viennent les chiffres : **de la phrase**, ou **proposés** par le modèle quand la
phrase nomme une sorte de marché sans chiffres (« prudent », « comme en 2008 ») — la
carte le dit (« chiffres proposés, à vérifier ») et la note dit ce qui a été supposé.
Rien ne change avant « Appliquer » (ou « Appliquer et garder », qui l'enregistre aussi
comme scénario de marché), et le toast rétablit le barème et la volatilité d'avant.
