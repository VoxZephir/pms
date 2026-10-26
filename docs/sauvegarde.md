# Sauvegarde chiffrée (`backup.py`, `--backup`, `--restore`)

<!-- Chiffrée le 15.10.2026. Avant, chaque lancement déposait un zip en clair
     de data/ et inbox/ dans OneDrive. -->

**Ce qui est copié et pourquoi.** Le ledger se reconstruit depuis les relevés ; les
décisions non — corrections, règles perso, budgets, plans, calage crypto. `run.bat`
appelle `--backup` à chaque lancement ; une copie n'est écrite que si quelque chose a
changé (empreinte des noms et contenus, pas des dates), et les dix dernières sont
gardées.

**Pourquoi chiffrer.** La destination par défaut est OneDrive : le nuage d'un tiers. Un
zip en clair y mettait chaque relevé, IBAN et correction à la portée de quiconque lit ce
compte — un trou plus concret que toute question d'hébergement de l'app.

**Comment.** Fernet (AES-128 + HMAC-SHA256) de `cryptography`, que pdfminer installait
déjà ; nommé dans `pyproject.toml` pour ne pas reposer sur le choix d'un autre paquet.
Le zip est construit et chiffré en mémoire : la version en clair ne touche jamais le
disque. Fichiers `pms-AAAAMMJJ-HHMMSS.zip.enc`. Pour savoir si rien n'a changé, la
dernière copie est déchiffrée et son commentaire (l'empreinte) relu ; une copie sous une
autre clé ne peut pas en témoigner, une nouvelle est écrite.

**La clé.** Aléatoire, `data/backup.key`, créée au premier `--backup`, **jamais mise
dans une archive** — une copie qui porterait sa clé ne fermerait rien. Jamais imprimée
non plus (la console est l'endroit d'où partent les captures d'écran) : la CLI nomme le
fichier, l'utilisateur l'ouvre et en recopie le contenu dans son gestionnaire de mots de
passe. Sans cette seconde copie, après un disque perdu, les sauvegardes sont du bruit.

**Les copies d'avant le chiffrement** (`pms-*.zip`) ne sont jamais effacées par le code :
ce sont les seules que l'ancienne méthode savait restaurer, et les retirer est la
décision de l'utilisateur une fois la clé rangée. `--backup` les signale à chaque passage
tant qu'elles existent.

**Restaurer.** `python -m pms --restore ARCHIVE [--into DOSSIER]`. La clé est lue dans
`data/backup.key` ; sur un clone neuf, elle est demandée (saisie sans écho). Rien n'est
jamais écrasé : un seul fichier déjà présent arrête toute la restauration avant la
moindre écriture — restaurer par-dessus un `data/` vivant remplacerait les corrections
récentes par des anciennes. Par défaut à la racine du dépôt ; ailleurs dans le dépôt,
refusé (`data/` et `inbox/` n'y seraient pas exclus de git).

## Relire la copie, pas seulement l'écrire

Écrire une copie ne prouvait rien de sa relecture : une clé remplacée à la main, un
client de synchronisation qui tronque le fichier, et le premier signe aurait été le jour
du disque perdu. La copie la plus récente est donc **relue comme une restauration**
(`backup.verify`) : déchiffrée, la somme de contrôle de chaque fichier vérifiée,
l'empreinte recalculée sur le contenu et comparée à celle scellée dans l'archive. Cela
arrive à chaque nouvelle copie, et une fois par semaine sinon (`VERIFY_EVERY`).

L'issue de chaque passage est écrite dans `data/backup_status.json`, exclu de l'archive
(l'écrire n'est pas un changement). L'app n'en parle que s'il y a un problème
(`backup.health`, champ `backup` de `/api/meta`), dans la barre latérale et sur le tableau
de bord :
- **« Sauvegarde en échec »** : le dernier passage a échoué, ou la copie ne se relit pas ;
- **« Sauvegarde ancienne »** : aucun passage depuis deux semaines (`run.bat` sauvegarde à
  chaque lancement) ;
- **« Aucune sauvegarde »** : aucun passage enregistré.
