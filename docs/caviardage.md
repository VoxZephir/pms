# Caviarder un PDF (20.10)

`redact.py`, `python -m pms --redact`, `caviarder.bat`. Un outil à côté de l'app : avant
d'envoyer un relevé (à une banque, à un conseiller, pour brancher le parser d'une autre
banque), en retirer ce qui dit qui le détient.

## Ce qui est retiré

- **Les IBAN**, reconnus par leur chiffre de contrôle (ISO 13616, modulo 97) : un numéro
  qui en a la forme sans en avoir la clé reste. Tout ce qui suit le mot « IBAN » part aussi,
  et le numéro de client.
- **Les noms que le relevé porte**, quand PMS sait le lire (aujourd'hui le PDF Swissquote) :
  le titulaire, mot à mot aussi (un nom de famille seul, un nom coupé en fin de ligne), et
  la contrepartie de chaque mouvement qui n'est pas un paiement par carte — employeur,
  régie, personne. **Les commerces payés par carte restent** : ils ne disent rien du
  titulaire, et c'est ce qui rend le relevé encore utile.
- **Dans n'importe quel PDF**, le nom d'une personne : un prénom courant (une liste dans le
  code, sans accents ni casse) à côté d'un mot à majuscule (« Jean Dupont », « DUPONT
  Jean »), ou un nom après une civilité (M., Mme, Monsieur, Herr, Dr…) ; une adresse (une
  rue et son numéro, un NPA et sa ville seuls sur une ligne).
- **Les motifs de `data/local_rules.json`** : ce sont les règles qui nomment un employeur,
  une régie, un praticien ou une personne.
- `--also "Nom, Autre nom"` en ajoute ; `--spare "Swissquote"` en épargne (dans la page, une liste : un terme par ligne, ou séparés par des virgules ou des points-virgules).

Un nom qui n'est ni dans le relevé, ni après une civilité, ni porté par un prénom de la
liste, ni dans les règles locales peut rester : **parcourir le PDF avant de l'envoyer
reste la dernière vérification**, et `--also` le rattrape.

## Comment

PyMuPDF réécrit le contenu de la page : un mot caviardé **n'est plus dans le fichier**, pas
caché sous un rectangle qu'un copier-coller traverserait. Les métadonnées (auteur, titre,
XMP), les pièces jointes et les scripts sont effacés (`scrub`), les objets orphelins
ramassés à l'enregistrement. La copie est ensuite relue : si un passage retiré y est encore
lisible, l'outil échoue et supprime la copie plutôt que d'en laisser une fausse.

Le texte est lu par blocs, chaque caractère rattaché à son mot : une correspondance
trouvée dans le texte devient des rectangles sur la page, même sur un nom qui passe à la
ligne. Les images (un logo) restent intactes.

Le rapport ne cite jamais un nom en clair : « D***** G******* », assez pour reconnaître
ce qui est parti.

## Où

**Dans l'app, `/caviarder`** (« Caviarder un PDF », sous « Plus ») : déposer un PDF, des
termes à retirer ou à laisser, « Caviarder », puis télécharger la copie
(`web/api/redaction.py`). L'original ne passe que par un dossier temporaire, jamais
`inbox/` ; seule la copie reste, dans le même dossier que la CLI, et la page liste les
dernières. Le rapport y masque les noms comme en console. Sans PyMuPDF, la page le dit et
le bouton est éteint.

`output/caviarde/<nom>-caviarde.pdf` : gitignoré, et jamais `inbox/`, où une copie serait
ingérée. `caviarder.bat` : glisser un ou plusieurs PDF dessus ; il installe la dépendance
et ouvre le dossier.

**PyMuPDF est dans le groupe `dev`** (`pyproject.toml`) : l'app ne l'installe pas à son
lancement ; `caviarder.bat` et `run.bat --test` le font. La série 1.x n'a aucune
dépendance propre (la 2.0 en tire treize). Sa licence est l'AGPL : sans effet pour un outil
personnel, à peser avant tout usage commercial.

## Accents et noms coupés (27.10)

Le relevé réel était refusé : quatre noms « encore lisibles ». La recherche comparait les
noms tels quels (« Genève » ne trouvait pas « GENEVE »), la relecture sans accents ni
casse : un nom retiré à un endroit restait à un autre, et la relecture le voyait. Deux
changements :

- **la recherche se fait sur le texte replié** (`fold_same` : sans accents ni casse,
  caractère pour caractère, pour que la position trouvée retombe sur les mots de la page) ;
  les règles personnelles restent des expressions lues sur le texte tel quel, comme les
  catégories les lisent ;
- **un nom encore lu est retiré au tour suivant**, depuis l'original : en entier, ses mots
  séparés par n'importe quoi (un tiret, une fin de bloc, rien), et mot par mot (quatre
  lettres au moins). Trois tours au plus, puis le refus, comme avant. La relecture
  cherche des mots entiers : un nom dans un mot plus long n'est pas lui.

Les deux cas ont leur test, qui échoue sans le changement.

**Le numéro de client** (27.10) : la règle « Client 1234567 » ne le voyait pas quand le
libellé et le numéro sont dans deux blocs de la page de garde. Le numéro que le relevé a
donné à la lecture est désormais cherché partout, chiffre à chiffre (espacé, ou dans un
mot plus long, qui part en entier), et relu de même.
