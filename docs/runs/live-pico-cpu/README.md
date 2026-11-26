# pico sur un modèle de 1,5 milliard, sans carte graphique

Ce dossier publie un **échec mesuré**, pas une réussite. Il existe parce que la promesse « pico tourne sur
un 1,5B » a été faite sans preuve, et que la mesure dit autre chose.

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

| Modèle | Où | Résultat |
| --- | --- | --- |
| `qwen2.5:1.5b-instruct` | NAS, CPU | lit, puis boucle sur `fs_read`, arrêt `blocked` |
| `qwen2.5:3b-instruct` | NAS, CPU | même boucle, arrêt `blocked` |
| `qwen/qwen3-vl-8b` | carte 3 Go | trois étapes, `pico.md` écrit, `done` |

Ce que ça dit : la boucle et le garde-fou anti-boucle fonctionnent, la sortie est propre et rien n'est
présenté comme réussi. Ce que ça dit aussi : **un modèle de 1,5 à 3 milliards ne suit pas un protocole
d'appel d'outils en JSON**, même sur un chemin de deux étapes. Il faut un modèle qui sait produire un
appel d'outil structuré, et c'est une contrainte de modèle, pas de code.

## Ce que le dépôt ne prétend plus

La phrase « conçu pour tourner sur un 1,5 milliard » a été retirée du README, du README de `live-pico` et
de `JURY.md`. À la place : le run de référence est fait sur un 8B en 4 bits, et le comportement des petits
modèles est publié ici, avec son journal.
