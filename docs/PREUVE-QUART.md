# Preuve longue : une session de quart

Toutes les autres preuves de ce dépôt tiennent en minutes. Celle-ci tient une session de travail réelle :
plusieurs heures, sans opérateur, avec des pannes provoquées.

## Protocole

1. Un modèle local tourne sur LM Studio, machine de 3 Go, `qwen2.5-coder-7b-instruct` en Q4.
2. Une boucle relance un run dès que le précédent finit, en alternant les scénarios qui écrivent des
   livrables : `cyber-brief`, `dataset-report`, `local-audit`, `capture-audit`.
3. Trois interruptions sont provoquées à des moments tirés au hasard : le processus est tué, puis
   relancé avec `--resume`. Une interruption au moins tombe pendant une écriture de livrable.
4. À la fin, les chiffres sont produits par le dépôt lui-même :

```
python3 docs/production/serie_quart.py --data ./data --svg docs/production/courbe-quart.svg
```

Le script ne compte que ce qui existe sur disque. Il liste les échecs par leur nom, il ne les résume pas
en pourcentage.

## Ce qui sera publié

| Mesure | Source |
| --- | --- |
| nombre de runs et de passes | `data/runs/*.json` |
| taux de livrable (fini et artefact présent) | champs `status` et `artifacts` |
| p50 et p95 par run | `duration_s` |
| reprises réussies | `state.json` avec `resumed_at` |
| procédures apprises | étapes `skill_write`, fichiers de `data/skills/` |
| échecs nommés, avec leur raison | liste exhaustive, sans filtre |

## Résultats

À remplir après la session. Aucun chiffre n'est avancé avant d'avoir été mesuré, et si la session ne
tient pas, ce document dira pourquoi plutôt que d'annoncer un chiffre.

- date de la session :
- durée réelle :
- modèle et quantification :
- runs / passes :
- taux de livrable :
- p50 / p95 :
- reprises réussies sur interruptions :
- procédures apprises :
- échecs, nommés :

Le graphe cumulatif est écrit dans `docs/production/courbe-quart.svg`.

## Ce que cette preuve ne prouve pas

Elle ne prouve pas que l'agent est bon : elle prouve qu'il tient dans le temps sans surveillance, qu'il
reprend après un arrêt brutal et qu'il garde une trace vérifiable. Un modèle plus gros produirait de
meilleurs livrables, pas une meilleure tenue.
