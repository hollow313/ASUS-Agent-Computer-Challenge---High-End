# Runs réels sur la GTX 1060 3 Go : ce que la carte refuse de faire

Trois runs ont été lancés le 25 novembre 2026 sur la machine de production, avec un modèle réellement
chargé dans Ollama, sans cassette, sans fixture de décision, sans clé d'API. Matériel : NVIDIA GeForce
GTX 1060 3 Go (Pascal, 3072 Mio), pilote 550.142, Ollama sur le réseau local.

Les trois se sont arrêtés en `blocked`. Ce document publie les trois, avec leurs journaux, parce qu'un
agent qui s'arrête proprement est une information, et parce que la carte de 3 Go a une limite précise
qu'il vaut mieux montrer que taire.

## 1. Protocole

| | |
| --- | --- |
| Modèles | `qwen2.5:1.5b-instruct` (986 Mo, Q4_K_M) et `qwen2.5:3b-instruct` (Q4_K_M) |
| Serveur | Ollama local, API compatible OpenAI, aucun accès cloud |
| Commande | `python3 -m agentdemo run --scenario <nom> --live --model <modèle> --base-url http://<nas>:30068/v1 --timeout 300` |
| Décisions | prises par le modèle, étape par étape, sans trace préenregistrée |
| Journaux | [`docs/runs/live-gtx1060/`](runs/live-gtx1060/) |

## 2. Les trois runs

| # | Scénario | Modèle | Durée | Étapes | Statut | Cause |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `cyber-brief` | qwen2.5 1.5B | 92 s | 5 | `blocked` | `rss_rank("feeds/*.rss")` : joker refusé, 3 appels identiques en échec |
| 2 | `cyber-brief` | qwen2.5 3B | 177 s | 5 | `blocked` | `fs_list("feeds")` 4 fois de suite, sans avancer |
| 3 | `dataset-report` | qwen2.5 3B | 94 s | 5 | `blocked` | `fs_list` 4 fois de suite, sans avancer |

### Run 1, 1,5B sur la veille cyber

Le modèle appelle `rss_rank` avec un joker (`feeds/*.rss`) au lieu des trois chemins exacts. L'outil
refuse et **nomme les fichiers présents** (`cert.xml`, `media.xml`, `vendors.xml`), ce qui est la bonne
réponse. Le modèle ne corrige pas, rappelle le même joker, tente un outil vide, puis se bloque au
troisième appel identique en échec. Aucun briefing n'est écrit.

### Run 2, 3B sur la veille cyber

Même scénario, modèle plus gros : il liste `feeds` correctement du premier coup, puis **recommence trois
fois** au lieu de lire les fichiers listés. La relance du garde-fou lui dit explicitement d'avancer ; il
continue. Blocage au quatrième appel identique, budget restant intact.

### Run 3, 3B sur l'analyse de données

Scénario plus simple (un CSV, un graphique, une note) : même symptôme, `fs_list` en boucle. Le modèle
liste, voit le fichier, et ne passe pas à la lecture.

## 3. Ce que ces runs prouvent

- **Le garde-fou fonctionne.** Dans les trois cas, l'agent s'arrête au lieu d'écrire un livrable vide ou
  inventé. Le statut est `blocked`, le bilan nomme l'outil et le nombre d'appels, et les artefacts sont
  vides : rien n'est publié qui ressemble à un succès.
- **Les erreurs sont lisibles.** Le refus de joker dit exactement quels fichiers existent ; un agent qui
  reçoit ce message a de quoi se corriger. C'est le modèle qui ne le fait pas, pas l'outil qui se tait.
- **Les temps sont réels.** 92 à 177 secondes pour cinq étapes, sur une carte de 3 Go : c'est le prix
  d'un petit modèle, et il est publié tel quel.

## 4. Ce que ces runs ne prouvent pas

- **Que la boucle ne marche pas.** Les mesures du dépôt et la campagne du 24 novembre montrent des runs
  complets avec un 7B Q4 en offload partiel. Ici, les modèles testés tiennent **entièrement** dans 3 Go,
  mais ne savent pas enchaîner : la taille qui rentre n'est pas la taille qui raisonne.
- **La qualité d'un briefing.** Aucun livrable n'a été produit, donc il n'y a rien à juger.
- **Le comportement d'un 7B ou d'un 8B sur cette carte.** Ces runs n'ont pas été refaits ici : sur
  3 Go, ils passent par l'offload CPU, ce qui allonge chaque étape au-delà du budget de temps de cette
  campagne. Les chiffres publiés le 24 novembre restent la référence pour ces modèles.

## 5. Ce que ça dit du matériel

C'est l'argument le plus concret du dossier, et il est négatif : **3 Go de VRAM ne suffisent pas à faire
tourner un agent qui enchaîne**. Il faut soit un modèle plus gros avec offload (lent), soit une carte qui
fait tenir un 7B ou un 14B sans réfléchir au contexte. Un 14B en Q8 tient dans 16 Go ; un 32B en Q4 tient
dans 32 Go. Ce n'est pas une préférence, c'est la différence entre un agent qui boucle et un agent qui
liste un dossier quatre fois.

---

*Les journaux bruts sont dans [`docs/runs/live-gtx1060/`](runs/live-gtx1060/). Chaque fichier contient les
étapes, les arguments, l'observation reçue et la durée de chaque appel modèle.*
