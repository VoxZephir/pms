# Impôts

La page `/impots` (`taxes.py`, `web/api/taxes.py`) dit, pour une année, ce que le relevé
apporte à la déclaration : chaque déduction avec la règle qui en fait une et les lignes
derrière elle, le salaire versé, les intérêts, la fortune au 31.12, les impôts payés.
`/impots/<année>.xlsx` en fait un classeur : une feuille de synthèse, une feuille des
lignes.

**Ce n'est pas la déclaration.** Les attestations (certificat de salaire, 3a, décompte de
la caisse maladie, reçus des dons) font foi ; la page dit où regarder et à peu près
combien. Chaque rubrique porte son degré de certitude :

| Marque | Sens |
|---|---|
| exact | le relevé suffit (le 3a versé, plafonné) |
| forfait | la déduction est un montant fixe, quel que soit le payé (primes d'assurance) |
| estimé | lu dans le relevé, à vérifier ligne à ligne (frais de maladie, dons, formation) |
| à trier | le relevé ne sait pas quelle part compte (transports : seul le trajet domicile – travail) |

## Les règles

Celles de l'impôt fédéral direct pour une personne salariée seule (`taxes.RULES`, ESTV ;
inchangées en 2026 selon la circulaire 215). Une année au-delà de la table reprend la
dernière connue et le dit. Les cantons ont leurs propres montants : la page le rappelle,
elle ne les code pas.

- **3a** : versé dans l'année, jusqu'au plafond avec une caisse de pension (`fiscal.py`).
- **Primes d'assurance** : un forfait (1'800 CHF avec un 2e pilier ou un 3a, 2'700 sans),
  presque toujours dépassé par la seule LAMal.
- **Frais de maladie** : la part restée à la charge, au-delà de 5 % du revenu net. La
  part est celle de `health.care_by_year` (`docs/a-venir.md`) : payé aux soignants, plus
  ce que la caisse refacture au-delà de la prime, moins ses remboursements.
- **Dons** : à des institutions repérées à leur nom (`taxes.DONATIONS`) ou classées dans
  une sous-catégorie « Dons » par une règle personnelle ; 100 CHF au moins dans l'année,
  20 % du revenu net au plus.
- **Formation continue** : repérée au nom de l'école, plafonnée.
- **Transports** : tous les billets et abonnements de transports publics, sans déduction
  calculée : seul le trajet domicile – travail compte, le relevé ne le distingue pas.

**Le revenu net** fixe deux seuils (maladie, dons). Faute de mieux, la page part du
salaire versé moins le 3a ; celui de la dernière taxation est plus juste et se tape
(`?net=`). **Le salaire** est un revenu de la catégorie « Revenus » d'au moins 1'000 CHF
dans l'année et de 500 CHF par versement en moyenne : un ami qui rembourse deux fois n'est
pas un employeur. C'est le net versé ; le certificat donne le brut à déclarer.

La fortune au 31.12 est celle du panneau Épargne (`fiscal.year_end`) : valeurs de l'app,
proches des cours de fin d'année de l'AFC, pas identiques. La page s'ouvre sur l'année
précédente, celle qu'on déclare au printemps.

## En chemin : les règles ne lisent plus l'adresse

Les règles de catégorie lisaient le type de paiement, le bénéficiaire **et** sa
localisation. Une localisation est une adresse aussi souvent qu'une ville, et une rue
porte le nom de n'importe quoi : sur le relevé fictif, le salaire d'un employeur établi
« Rue du Musée » était classé en sorties culturelles (donc remboursement de loisirs, pas
revenu), et un burger « Rue de l'Hôpital » en frais de santé. `categories._searchable`
ne lit plus que le type et le bénéficiaire.

## Genève (19.10)

Le canton se choisit sur la page Impôts, avec l'année à partir de laquelle on y déclare ;
à Genève, l'impôt d'une année se paie l'année suivante. Le canton, l'année de départ et
ce décalage se règlent sur la page
(`data/tax.json`, jamais en dur). À partir de l'année choisie, chaque rubrique porte deux
déductions, fédérale et cantonale (`taxes.CANTONS`) :

| Rubrique | Genève (ICC) |
|---|---|
| Frais de maladie | au-delà de **0,5 %** du revenu net (LIPP art. 32), contre 5 % au fédéral |
| Trajets domicile – travail | plafonnés à **529 CHF** par an, quel que soit le moyen de transport |
| Primes d'assurance | les primes payées, jusqu'à 6'864 CHF pour une personne seule |
| Dons | jusqu'à 20 % du revenu net |
| 3a | comme au fédéral |
| Formation continue | plafond fédéral faute du cantonal |

Les montants ont été lus sur ge.ch le 19.10.2026 ; le plafond des primes vient d'un
barème ICC dont l'année n'est pas imprimée, et le minimum des dons comme le plafond de la
formation n'ont pas été trouvés : ces lignes portent « à vérifier ». Un projet de loi
(PL 13194) voulait supprimer la franchise de 0,5 % sur les frais médicaux ; son sort en
2026 n'est pas connu. Le guide de l'année (lien sur la page) fait foi.

**Les impôts d'une année** sont, quand le décalage est coché, les paiements de l'année
suivante : la page de 2026 montre ceux de 2027, et dit qu'ils viendront tant que le relevé
n'y est pas.

## Titres hors relevé (20.10)

Une action non cotée reçue ou achetée (la part d'une société locale, un cadeau) n'apparaît
dans aucun relevé, mais elle entre dans la fortune et son dividende dans le revenu. Elle
se déclare sur la page Impôts (`holdings.py`, `data/holdings.json`) : nom, nombre de
titres, année d'entrée, **valeur fiscale d'un titre au 31.12** année par année (une année
vide reprend la précédente), et le bénéficiaire tel que le relevé imprime le dividende.

- La fortune au 31.12 l'ajoute, à sa valeur déclarée (une ligne « titre » dans le
  tableau et dans l'export).
- Le dividende est retrouvé dans le relevé par le nom du payeur. **Une société suisse
  verse net de 35 % d'impôt anticipé** : 65.00 reçus sont 100.00 bruts (65.00 / 0,65), qui
  se déclarent dans l'état des titres, et 35.00 d'impôt anticipé que la déclaration
  rembourse. La page et l'export donnent les trois chiffres.
- L'indépendance financière (Prévisions) compte le titre dans le patrimoine.

Le versement lui-même se classe « Revenus · Dividendes » : la règle publique attrape une
ligne qui dit « Dividende » ; une ligne qui ne porte que le nom de la société (le cas
courant) se classe une fois depuis sa fiche, « Tout ce bénéficiaire », et la règle suit
les années suivantes. Sinon un mot courant du nom de la société, qu'une règle publique
reconnaît, peut la ranger ailleurs.

Le titre n'entre pas dans le panneau Épargne, qui suit des comptes valorisés au jour le
jour ; une valeur fiscale annuelle n'y a pas sa place.
