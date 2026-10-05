# Reclassement en masse et fusion de bénéficiaires

<!-- Détaché de CLAUDE.md le 22.09.2026 : lu à la demande, quand on
     travaille sur ce sujet (voir « Où lire avant de toucher »). -->

Le cas utile n'est pas « les 60 lignes affichées » mais « les 443 du filtre courant ».
`views.common._filtered()` est donc partagé entre la table et l'endpoint bulk : « tout ce qui
correspond » désigne exactement ce que l'écran montrait, sans dérive possible.

Les cibles du bulk sont préfixées `to_*` (`to_category`, `to_bucket`). Elles partageaient
d'abord les noms du filtre (`category`, `bucket`), ce qui faisait de « tout ce qui est
dans le bucket X » et « déplacer vers le bucket Y » le même paramètre — la sélection
revenait vide.

Un bulk fait un seul `save()` : 443 corrections écrites une à une réécriraient le fichier
443 fois, et un plantage à mi-parcours laisserait une correction à moitié appliquée que
rien n'enregistre comme incomplète.

**Les Twint sans bénéficiaire se trient à la main, une touche chacun** (`/reclasser/tri`).
Sur le relevé réel, 313 paiements Twint n'impriment que « Paiement Twint » : ni
bénéficiaire, ni message, ni lieu. Ils étaient rangés en « Transferts P2P », ce qui
affirmait ce que personne ne sait — Twint paie aussi les parcmètres et les machines à
café, et 82 d'entre eux valent ~2 CHF. Ils sont désormais « Twint non identifié »
(`categories.TWINT_UNKNOWN`, bucket non classé) ; « Transferts P2P » ne garde que les
virements à une personne nommée.

Aucune règle ne peut les classer, et aucun modèle non plus : l'information n'est pas sur
la ligne. La page rend donc le tri manuel peu coûteux plutôt que de le deviner :

- un Twint à la fois, le plus récent d'abord (celui dont on se souvient) ; une catégorie
  = une touche 1–9, `S` passe, `Z` annule le dernier. Chaque touche clique un vrai bouton
  de formulaire : sans JavaScript la page fait la même chose ;
- pour rafraîchir la mémoire : le jour de la semaine, les autres mouvements du jour
  (souvent une carte avec un lieu), et **ce que le titulaire a déjà décidé au même
  montant** — la seule piste honnête, puisque le montant est tout ce que la ligne porte.
  Elle est *montrée* (bouton souligné), jamais appliquée d'office ;
- les montants récurrents (au moins `TRIAGE_GROUP_MIN` = 3) se classent d'un coup, par le
  même `/reclasser/bulk` que la table, en épingles ;
- les catégories viennent dans l'ordre de ce qui a déjà servi pour des Twint, pour que
  les touches tombent sur les habituelles.

Chaque choix est une épingle, pas une règle : il n'y a pas de bénéficiaire sur lequel
écrire une règle. **Et l'épingle garde le bucket déjà décidé** : 153 des Twint réels
portaient une épingle Want/Need sans catégorie, posée dans la table. `pin()` remplace
l'entrée entière, donc y écrire une catégorie aurait re-dérivé le bucket de la catégorie
(Transport → Need) et défait la décision — 50 d'un coup avec « Classer les 50 ». Le tri
écrit donc la catégorie *par-dessus* le bucket existant (`_pin_category`), son annulation
rend l'épingle bucket seul, et les groupes par montant passent par le tri, pas par
`/reclasser/bulk`. Le tri refuse (409) toute ligne qui n'est pas un Twint non identifié.

En chemin : l'envoi en place des formulaires POST (`app.js`) construisait `FormData(form)`
sans le bouton qui soumettait — un formulaire à plusieurs boutons nommés arrivait sans le
choix, en 400. Le bouton est maintenant ajouté (`ev.submitter`).

**Les alias fusionnent plusieurs orthographes d'un même bénéficiaire.** Les banques ne sont
pas cohérentes — la même régie est imprimée « Muster Verwaltung AG » et
« Muster Verwaltungs AG », et tous les totaux la comptent alors comme deux personnes.
Deux formes : un alias exact, et un alias par motif pour toute une enseigne (40 orthographes
de Coop sur ce relevé, une par caisse — les lister une à une serait une liste qui grandit
chaque mois). L'exact l'emporte sur le motif, étant la déclaration la plus spécifique.

Les alias s'appliquent *avant* les règles, pour qu'une règle écrite sur le nom conservé
attrape aussi les autres. Ils ne s'enchaînent jamais : poser A→B puis B→C repointe A sur C.

**La fusion ne déplace pas de catégorie.** `classify_all` tourne avant `overrides.apply`,
donc une station-service Coop reste en transport même si elle s'affiche « Coop ».
`top_merchants` reporte alors la catégorie qui porte l'argent, pas celle de la première
ligne — et ne signale un mélange que sous 95 %, sinon « 2 catégories, 100 % » énonce
quelque chose de faux.
