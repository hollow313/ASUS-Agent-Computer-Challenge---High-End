# Journal de la veille

Une ligne par exécution réelle, produite par `docs/production/veille.py`, jamais écrite à la main. Les
jours sans run resteront visibles avec le statut `absent` : c'est cette honnêteté qui rend la série
crédible. Le tableau se recalcule avec `python3 docs/production/serie.py`.

| Date | Statut | Durée | Étapes | Livrable | Modèle |
| --- | --- | --- | --- | --- | --- |
| 2026-11-25 | done | 3 min 29 | 5 | briefing.md, 8 items | qwen/qwen3-vl-8b |

## Comment lire une ligne

- **Statut** : `done` veut dire qu'un briefing a été écrit **et** qu'au moins une source a été lue. Un
  briefing vide, ou un run sans lecture réseau, sort en `vide` : il ne compte pas comme une réussite.
- **Étapes** : les trois premières sont imposées par le contrat du scénario (lecture des sources), les
  suivantes sont décidées par le modèle.
- **Livrable** : le nombre d'items est celui des entrées numérotées qui portent un lien.

Les tentatives intermédiaires du 25 novembre qui ont échoué (contexte dépassé, briefing vide) sont dans
l'historique git avec leurs dossiers ; elles ne sont pas recopiées ici parce que leur trace n'existe plus
sur disque, et une ligne de journal sans dossier correspondant ne prouverait rien.
| 2026-11-25 | done | 0 min 55 | 5 | briefing.md, 3 items | qwen/qwen3-vl-8b |
| 2026-11-25 | done | 0 min 44 | 5 | briefing.md, 3 items | qwen/qwen3-vl-8b |
| 2026-11-26 | absent | — | — | aucun (machine éteinte) | — |
