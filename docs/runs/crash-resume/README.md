# Le processus est tué au milieu, et il reprend

Cette trace n'est pas une simulation. Le processus a reçu un `kill -9` pendant l'exécution, puis a été
relancé avec `--resume`, et il a continué à l'étape suivante.

## Les commandes

```bash
export AGENTDEMO_DATA_DIR=/tmp/crash2
python3 -m agentdemo run --scenario cyber-brief --live --model qwen2.5-coder-7b-instruct \
  --base-url http://127.0.0.1:1234/v1 &
kill -9 $!                                  # pendant l'exécution, après la première étape
python3 -m agentdemo run --scenario cyber-brief --live --model qwen2.5-coder-7b-instruct \
  --base-url http://127.0.0.1:1234/v1 --resume 02a977d6b1
```

## Ce qu'on voit dans les deux journaux

Avant le kill : l'agent liste les flux, se trompe une fois, corrige. L'état est écrit après chaque étape
(écriture atomique), donc le deuxième appel réussit et le run continue.

Après la reprise : la numérotation ne repart pas de zéro, elle reprend à l'étape 3. Le livrable est écrit,
le statut passe à `done`.

| Moment | Fichier |
| --- | --- |
| sortie avant le kill | [`journal-avant-kill.log`](journal-avant-kill.log) |
| sortie après la reprise | [`journal-apres-reprise.log`](journal-apres-reprise.log) |
| journal d'étapes avant le kill | deux étapes faites, puis le processus meurt (voir le `.log`) |
| état du run après reprise | `step_index = 4`, statut `done` (le fichier est réécrit à chaque étape) |
| journal machine du run repris | [`journal.json`](journal.json) |
| livrable produit après reprise | [`briefing.md`](briefing.md) |

## Ce que ça prouve, et ce que ça ne prouve pas

Ça prouve que l'état suffit à reprendre sans rejouer les étapes déjà faites. Ça ne prouve pas qu'un run
tué au milieu d'une écriture de fichier reprend sans perte : le fichier peut être tronqué, et c'est pour ça
que les livrables sont réécrits entièrement plutôt que modifiés en place.

La vidéo de 30 secondes de ce même geste est dans [`../../video/vigie-crash-resume.mp4`](../../video/vigie-crash-resume.mp4).
