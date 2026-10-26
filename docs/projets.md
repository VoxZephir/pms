# Projets

La page `/projets` (`projects.py`, `web/api/projects.py`) rassemble des mouvements sous
un nom (un voyage, un déménagement, un mariage) et dit ce qu'ils ont vraiment coûté :
**dépensé moins remboursé**. Une part de voyage remboursée par Twint vient en moins du
voyage, au lieu de se perdre dans les revenus.

## Un projet est une liste de clés

Un projet est une liste de clés de mouvements (`overrides.key_of` : référence et devise,
l'identité qui survit à la réimportation), dans `data/projects.json`, à côté du ledger et
jamais dedans : comme une correction, c'est une décision du titulaire, pas ce que la
banque a imprimé. Un mouvement peut appartenir à plusieurs projets ; le relevé, lui, ne
change pas. Une ligne retirée du ledger (`--forget`) est comptée « manquante », pas
effacée du projet.

## Les voyages se proposent seuls

Un séjour à l'étranger est déjà lu par le tri des Twint (`twint.Context.stays` : des
achats par carte dans un pays étranger, sur deux jours au moins, chez deux commerçants au
moins, sites web exclus). Chacun est proposé comme projet avec :

- les achats par carte dans ce pays, du jour d'avant au jour d'après ;
- le vol et l'hôtel (« Avion & car longue distance », « Hébergement ») réservés dans les
  90 jours avant le départ ;
- les Twint reçus de 20 CHF ou plus dans les 14 jours après le retour, et les virements
  reçus d'une personne qui ne paie pas chaque mois (un employeur en est exclu) : les parts
  remboursées ;
- les Twint et virements de 100 CHF ou plus **envoyés** à quelqu'un pendant le séjour ou
  dans les trois semaines après : une part réglée, typiquement un Tricount soldé au retour
  (demande du titulaire, 19.10). Un Twint ne dit pas à qui ni pourquoi : la ligne le dit
  (« une part réglée (Tricount ?) ») et se décoche si ce n'en est pas une.

**Un séjour doit prouver qu'on y était** : deux paiements au moins sur place (repas,
hôtel, courses, taxi, pharmacie : `projects.ON_SITE`), et un pays n'est retenu que s'il
en a. Des sites qui facturent depuis l'étranger (abonnements, boutiques en ligne)
faisaient sinon un « voyage États-Unis · Pays-Bas » de n'importe quel mois (19.10).

**Chaque ligne dit pourquoi elle est là** (« sur place · Italie », « réservé 41 jours
avant le départ », « reçu 5 jours après le retour ») et la proposition dit sur quoi elle
repose (« 14 paiements sur place, 3 commerçants, 8 jours »). Elle s'ouvre avant d'être
créée : le nom se change, une ligne se décoche. « Ignorer » ne la propose plus
(`dismissed` dans `data/projects.json`, par date de départ et pays) ; l'annulation du
toast la fait revenir. Rien n'est rassemblé sans « Créer ». Un séjour dont une ligne est
déjà dans un projet n'est plus proposé.

## Les jours d'un projet

La durée et le coût par jour se comptent sur les dépenses du projet lui-même, hors
réservations et remboursements : un vol réservé en mai ne fait pas durer deux mois une
semaine de juillet.

## Ajouter, retirer

Depuis le projet, les mouvements des 30 jours autour (ou des dates données à la création
d'un projet vide), les plus proches d'abord, avec une recherche. Depuis la fiche de
n'importe quelle transaction, une puce par projet l'y ajoute ou l'en retire. Chaque
geste répond avec son annulation (`undo`), proposée dans le toast.

Les teintes des catégories sont celles des dépenses des projets, pas du ledger entier :
les loisirs, qui ne font pas partie des sept premières catégories du ledger, prenaient
sinon le gris d'« Autres » dans chaque voyage.
