# pico sans carte graphique : ce que chaque modèle donne

Ce dossier publie les quatre essais réels du même scénario `pico`, sur un Ollama sans GPU, avec quatre
modèles de tailles différentes. Deux échouent proprement, un réussit, et le quatrième est le run de
référence sur une carte. C'est cette page qui remplace la phrase « conçu pour un 1,5B », qui n'était pas
prouvée.

## Ce qui a été lancé

Ollama sur un NAS, sans GPU, modèle `qwen2.5:1.5b-instruct` (1,5 milliard de paramètres, quantification Q4) :

```bash
python3 -m agentdemo run --scenario pico --live --model qwen2.5:1.5b-instruct \
  --base-url http://192.168.1.200:30068/v1
```

## Ce qui s'est passé

Le modèle lit le fichier à l'étape 1, correctement, puis **rappelle `fs_read` avec les mêmes arguments**
quatre fois de suite. L'agent s'arrête de lui-même :

- statut : `blocked`
- étapes : 5, dont une en erreur (l'arrêt anti-boucle)
- bilan : Bloqué : fs_read a été appelé 4 fois avec les mêmes arguments, sans avancer. Le budget restant n'a pas été gaspillé.
- livrable : aucun

Journal complet : [`journal.json`](journal.json).

## Les trois modèles essayés

| Modèle | Où | Résultat | Étapes |
| --- | --- | --- | --- |
| `qwen2.5:1.5b-instruct` | NAS, CPU, sans GPU | boucle sur `fs_read`, arrêt `blocked` | 5 |
| `qwen2.5:3b-instruct` | NAS, CPU, sans GPU | même boucle, arrêt `blocked` | 5 |
| **`llama3.2:3b`** | **NAS, CPU, sans GPU** | **`done`, `pico.md` écrit en 4 min 21** | 5 |
| `qwen/qwen3-vl-8b` | carte 3 Go | `done`, `pico.md` écrit en 4 étapes | 3 |

Le run `llama3.2:3b` est le plus intéressant, et c'est celui qui compte pour un jury : sur une machine
**sans carte graphique**, il lit le fichier, se trompe une fois sur les arguments de `fs_write`, corrige, et
écrit le livrable. Journal : [`journal-llama32-3b.json`](journal-llama32-3b.json), livrable :
[`pico-llama32-3b.md`](pico-llama32-3b.md).

Ce que ça dit : la boucle, la reprise après une erreur d'outil et le garde-fou anti-boucle fonctionnent, et
un modèle de 3 milliards suffit sur un chemin de deux étapes, à condition qu'il sache produire un appel
d'outil structuré. Les deux `qwen2.5` de 1,5 et 3 milliards ne le savent pas : ils relisent le fichier
indéfiniment, et l'agent s'arrête en le disant au lieu de tourner jusqu'au budget.

## Ce que le dépôt dit maintenant

La phrase « conçu pour tourner sur un 1,5 milliard » a été retirée : elle n'était pas vraie. À la place,
trois faits mesurés, chacun avec son journal : un 8B sur carte termine en trois étapes, un `llama3.2:3b`
sans carte termine en cinq étapes avec une erreur corrigée, et deux `qwen2.5` de 1,5 et 3 milliards
s'arrêtent proprement sans livrable.
