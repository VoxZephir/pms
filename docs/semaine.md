# Le résumé de la semaine

`weekly.py` écrit la semaine en quelques lignes ; `notify.py` l'envoie au téléphone une
fois par semaine par **ntfy** (ntfy.sh, ou un serveur à soi sur le tailnet). Le réglage
et l'aperçu sont en bas de la page À venir (`pages/upcoming/Weekly.tsx`).

## Ce que dit le message

- la dépense des sept derniers jours **du relevé** (pas du calendrier : un relevé en
  retard ne fait pas une semaine vide), contre une semaine ordinaire, la médiane des
  semaines précédentes sur six mois ;
- les trois catégories qui ont pris le plus ;
- le mois en cours et sa fin probable (`lookback.month_pace`, le panneau « Le mois en
  cours » du tableau de bord), et les budgets dépassés ;
- ce qui tombe dans les sept prochains jours (`upcoming.commitments`), et les délais à
  30 jours ou moins (`upcoming.deadlines`) ;
- le cash projeté sous le seuil d'alerte de Prévisions, sur un an (`plans.floor_alert`,
  `docs/previsions.md`) ;
- un relevé vieux de plus de dix jours.

**Jamais un nom.** Le message traverse un serveur de notifications : il dit « assurance
maladie 431 le 05.08 », pas le nom de la caisse ; « loyer », pas la régie. Le titre ne
s'écarte de « Ta semaine » que d'un écart de 15 % ou plus.

## L'envoi

- **Le sujet est le seul secret** : qui le connaît lit les résumés. Il est tiré au
  hasard (`notify.new_topic`) à la première activation, affiché dans l'app pour que le
  téléphone s'y abonne, retiré d'un clic. Il n'apparaît dans aucun message d'erreur ni
  journal.
- **L'horloge** tourne dans le processus qui sert, comme la surveillance des
  Téléchargements : jamais dans le superviseur du reloader, jamais sous `create_app` (la
  suite de tests n'en démarre aucune). Elle regarde toutes les cinq minutes si le
  créneau de la semaine (jour et heure choisis) est passé sans envoi.
- **Un envoi raté** est noté et retenté une heure plus tard, jusqu'à ce qu'il passe ; la
  page montre la dernière erreur.
- Un toucher sur la notification ouvre l'app à l'adresse depuis laquelle le réglage a été
  enregistré (`app_url`).

Les réglages vivent dans `data/notify.json`.

## En chemin (19.10)

- **Les virements entre ses propres comptes** : un virement dont la contrepartie porte le
  nom du titulaire, lu sur le relevé (`Statement.holder`, jamais écrit dans le code), est
  un « Virement interne », ni revenu ni dépense (`categories.is_to_self`). Les mots du nom
  se comparent sans ordre ni accents (« DUPONT JEAN » est « Jean Dupont »). Un versement
  au courtier ou au 3a garde sa catégorie d'épargne ; une carte ou un Twint n'est jamais
  un virement à soi.
