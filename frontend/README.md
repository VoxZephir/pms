# Le front de PMS

L'app React que Flask sert. Les chiffres viennent de l'API JSON (`src/pms/web/api/`) ;
ici, on met en page et on dessine. Le raisonnement est dans `docs/app-web.md`.

## Travailler dessus

```bash
cd frontend
npm install          # une fois
npm run dev          # rebuild à chaque sauvegarde, dans src/pms/web/static/spa/
npm run build        # types vérifiés, puis le build à commiter
npm test             # tests unitaires (Vitest)
```

Le serveur Flask sert directement le dossier construit : pas de serveur de dev Vite, pas
de proxy. Après `npm run dev` ou `npm run build`, recharger la page suffit. Les fichiers
Python, eux, demandent un redémarrage du serveur.

**Le build est commité** (`src/pms/web/static/spa/`), pour que `run.bat` tourne sans
Node. Une modification de `src/` doit donc être suivie de `npm run build` et du commit
du dossier construit ; `tests/test_frontend.py` refait le build à côté et échoue si les
deux diffèrent.

## Où est quoi

| Dossier | Contenu |
|---|---|
| `src/shell/` | la coquille : barre latérale, onglets du téléphone, période, palette Ctrl K |
| `src/pages/` | une page par route ; les morceaux d'une grosse page dans un sous-dossier |
| `src/charts/` | colonnes, courbes, calendrier : la seule géométrie de graphiques de l'app |
| `src/components/` | primitives (`ui.tsx`), tables, feuilles, fiche d'une transaction |
| `src/lib/` | API, URL comme état, formats suisses, thème, types des réponses |
| `src/styles.css` | les tokens : couleurs validées, surfaces, ombres, en clair et en sombre |

Les huit couleurs catégorielles et les surfaces sont validées (contraste et daltonisme) :
ne pas en ajouter, ne pas toucher aux surfaces sans refaire la validation.
