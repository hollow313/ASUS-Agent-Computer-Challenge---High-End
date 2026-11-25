# Matériel : quatre paliers, mesuré ou projeté

Ce document distingue ce qui a été **essayé** sur la GTX 1060 3 Go du NAS et ce qui est **calculé** par
`python3 -m agentdemo fit`. Un palier projeté n'est pas un palier essayé, et le tableau le dit.

| Palier | Ce qui tient | Source |
| --- | --- | --- |
| 3 Go (GTX 1060, machine actuelle) | 7B Q4, 8B VL Q4, contexte court | mesuré, voir les mesures datées |
| 8 Go | 7B Q8, 14B Q4 | projeté par `fit` |
| 16 Go | 14B Q8, 32B Q4 | projeté par `fit` |
| 32 Go | 32B Q6, contexte 32 k | projeté par `fit` |

## Ce que la carte actuelle donne, mesuré

Dix tâches texte, dix tâches image, notation par correspondance exacte, température 0 :

| Suite | Cible | Réussite | p50 | p95 |
| --- | --- | --- | --- | --- |
| texte | Qwen 2.5 Coder 7B Q4 | 60 % | 0,75 s | 3,98 s |
| texte | Qwen3 VL 8B Q4 | 90 % | 0,67 s | 4,63 s |
| vision | Qwen3 VL 8B Q4 | 100 % | 0,94 s | 6,96 s |

Sources : [`mesures/mesures-20261121.md`](mesures/mesures-20261121.md) et
[`mesures/mesures-20261124-vision.md`](mesures/mesures-20261124-vision.md).

## GTX 1060 3 Go, la sortie de `fit`

```
carte simulée : 3.0 Go · contexte 8 k · marge runtime 1.5 Go

modèle                     taille        quant   mémoire    marge
-----------------------------------------------------------------
qwen2.5-coder-7b            7.6 B ne rentre pas     6.7 Go   -3.7 Go   (hors budget)
llama-3.1-8b                8.0 B ne rentre pas     7.5 Go   -4.5 Go   (hors budget)
qwen3-vl-8b                 8.2 B ne rentre pas     7.8 Go   -4.8 Go   (hors budget)
qwen2.5-coder-14b          14.7 B ne rentre pas    11.4 Go   -8.4 Go   (hors budget)
mistral-small-24b          23.6 B ne rentre pas    17.5 Go  -14.5 Go   (hors budget)
qwen2.5-coder-32b          32.8 B ne rentre pas    24.0 Go  -21.0 Go   (hors budget)
```

## 32 Go, la sortie de `fit`

```
carte simulée : 32.0 Go · contexte 32 k · marge runtime 1.5 Go

modèle                     taille        quant   mémoire    marge
-----------------------------------------------------------------
qwen2.5-coder-7b            7.6 B           Q8    11.7 Go   20.3 Go
llama-3.1-8b                8.0 B           Q8    14.6 Go   17.4 Go
qwen3-vl-8b                 8.2 B           Q8    15.4 Go   16.6 Go
qwen2.5-coder-14b          14.7 B           Q8    20.9 Go   11.1 Go
mistral-small-24b          23.6 B           Q6    26.9 Go    5.1 Go
qwen2.5-coder-32b          32.8 B           Q4    30.4 Go    1.6 Go
```

## Ce que la carte change dans l'agent

Trois choses, dans cet ordre : un modèle qui lit une capture sans être aidé, un contexte qui tient un
dossier entier plutôt qu'un fichier, et deux modèles en mémoire pour la revue par un second modèle ou
des sous-agents en parallèle. Aujourd'hui, la revue et les sous-agents fonctionnent, mais en séquentiel
et sur le même modèle.

## Ce que ce document ne dit pas

Aucun chiffre de débit n'est avancé pour les paliers 8, 16 et 32 Go : ils ne sont pas mesurés. Les
latences publiées viennent toutes de la carte de 3 Go, aux dates indiquées dans les rapports de mesure.
