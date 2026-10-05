# Export CSV et xlsx

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

**L'export est le filtre, pas la page.** `/export.csv` et `/export.xlsx` passent par
`_filtered()` et `_sorted()`, les deux mêmes fonctions que la table : le fichier contient
exactement les lignes qui étaient à l'écran, dans le même ordre, et pas seulement les 60
de la page courante.

**Deux formats parce qu'ils s'adressent à deux lecteurs.** Le CSV est un format
d'échange : virgule, point décimal, dates ISO, donc il se relit identiquement en pandas ou
en R. Pas d'apostrophe suisse ni de virgule décimale — ça, c'est pour l'écran. Sa seule
concession à Excel est le BOM UTF-8, sans lequel les accents arrivent en mojibake. Le xlsx
est celui qu'on double-clique : vraies dates, vrais nombres, une colonne se somme sans
nettoyage.

**Le xlsx est écrit à la main, sans dépendance.** Le sous-ensemble d'OOXML nécessaire ici
tient en quelques centaines de lignes de `zipfile` — une feuille, des chaînes en ligne,
quatre formats de cellule — et l'alternative était d'embarquer une bibliothèque tableur
pour un fichier que le programme écrit sans jamais le relire. Excel est pointilleux sur
trois détails qui font apparaître le dialogue de réparation : les deux premiers `fill`
doivent être `none` et `gray125`, chaque liste doit déclarer son `count`, et un
`autoFilter` veut son `_xlnm._FilterDatabase`. `tests/test_export.py` relit l'archive
plutôt que de faire confiance à l'écriture.

Les horodatages du zip sont figés : deux exports de la même fenêtre donnent des octets
identiques, donc un export se compare au précédent.

**L'écrivain xlsx fait N feuilles.** `to_xlsx` (transactions) est inchangé ;
`to_xlsx_sheets` produit N feuilles à colonnes arbitraires — une par table de
l'analyse. Les pièges Excel restent documentés : fills `none`/`gray125`,
counts déclarés, un `_xlnm._FilterDatabase` par feuille (`localSheetId`),
horodatages zip figés.
