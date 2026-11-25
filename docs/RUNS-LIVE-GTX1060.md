# Le même agent sur quatre backends : où est le vrai verrou

Quatre runs, un seul scénario (`cyber-brief`), le même code, les mêmes fixtures. Seuls le modèle et son
endpoint changent. Deux tournent en local sur la carte de la machine, deux tournent dans le cloud.

Le résultat tient en une ligne : **les deux modèles locaux qui tiennent entièrement dans 3 Go échouent,
les deux modèles cloud terminent.** Ce document explique pourquoi, sans arrondir.

## 1. Les quatre runs

| # | Modèle | Où | Durée | Étapes | Statut | Livrable |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | qwen2.5 1.5B Q4_K_M | local, GTX 1060 3 Go | 92 s | 5 | `blocked` | aucun |
| 2 | qwen2.5 3B Q4_K_M | local, GTX 1060 3 Go | 177 s | 5 | `blocked` | aucun |
| 3 | deepseek-chat | cloud | 11,4 s | 8 | `done` | `briefing.md` (1 935 o) |
| 4 | gemini-3.8-flash | cloud | 54,3 s | 13 | `done` | `briefing.md` |

Journaux bruts : [`docs/runs/live-gtx1060/`](runs/live-gtx1060/). Chaque fichier contient les étapes, les
arguments, l'observation reçue et la durée de chaque appel.

Les deux premiers runs ne sont pas des erreurs de configuration : les modèles sont chargés, répondent et
prennent des décisions. Ils échouent sur l'enchaînement. Le 1.5B appelle `rss_rank` avec un joker
(`feeds/*.rss`) que l'outil refuse en nommant les trois fichiers présents, puis répète le même appel. Les
deux 3B listent le dossier `feeds`, voient les fichiers, et **relistent au lieu de lire**. Le garde-fou
les arrête au quatrième appel identique, sans écrire de livrable vide.

## 2. Pourquoi le cloud a été utilisé, exactement

Ce n'est pas un choix de confort, et ce n'est pas le mode de fonctionnement du projet. C'est une
nécessité de méthode, pour une raison précise.

1. **Les modèles testés en local sont les plus gros qui tiennent entièrement dans 3 Go.** Un 1,5B et un 3B
   en Q4 pèsent 1 et 2 Go : ils restent sur la carte, sans débordement. Ce sont donc les seuls candidats
   honnêtes pour un test « 100 % local sur cette carte ».
2. **Ils ne savent pas enchaîner.** Le blocage ne vient pas de la mémoire, il vient du modèle : il
   n'utilise pas l'observation pour passer à l'étape suivante.
3. **Le modèle de référence du dépôt, le 7B en Q4, ne tient pas dans 3 Go.** Il pèse environ 4,4 Go : il
   tourne en débordement CPU, à 40 à 60 secondes par étape. C'est la configuration mesurée le 24 novembre,
   et elle reste la référence du dépôt, mais elle n'était pas exploitable pour une campagne de quatre runs
   dans le temps disponible, et elle ne permettait pas de comparer plusieurs tailles.
4. **Pour distinguer un bug de l'agent d'une limite de matériel, il faut faire varier un seul paramètre :
   la taille du modèle.** La carte ne peut pas charger un modèle plus gros que 3 Go sans débordement. Le
   cloud, si. Le contrôle a donc été fait là, avec le même code, le même scénario et les mêmes fichiers.

Autrement dit : le cloud n'est pas là pour faire joli ni pour remplacer le local. Il est là pour répondre à
une question que la carte ne permet pas de trancher : **est-ce que la boucle est cassée, ou est-ce que le
modèle est trop petit ?** Réponse : la boucle fonctionne, le modèle était trop petit.

## 3. Ce que ces quatre runs prouvent

- **Le code de l'agent n'est pas en cause.** Même code, même scénario, mêmes fixtures : avec un modèle
  capable, le run va au bout, écrit le livrable, le relit et enregistre une procédure.
- **Le facteur limitant est la taille du modèle qui tient en mémoire.** 1,5B et 3B : échec. Modèles de
  classe supérieure : succès, en 8 et 13 étapes.
- **Le garde-fou est réel.** Sur les deux échecs, le run s'arrête proprement en `blocked`, sans livrable
  inventé. Sur le premier run Gemini, lancé avec 8 étapes, le statut est `budget` : l'agent s'arrête aussi,
  et il suffit de lui donner 14 étapes pour qu'il termine. La limite est visible, pas silencieuse.
- **Le coût du local est en secondes, pas en euros.** 92 à 177 s pour cinq étapes sur la carte, contre 11
  à 54 s pour un run complet dans le cloud. C'est le prix de la souveraineté, et il est publié.

## 4. Ce que ces runs ne prouvent pas

- **Que le cloud soit une option acceptable pour ce projet.** Le projet est local par construction : les
  documents, les clés et les journaux ne sortent pas. Les deux runs cloud servent de contrôle, pas de mode
  d'emploi.
- **Qu'un 7B ou un 8B local ne sait pas faire.** Ils n'ont pas été testés ici, pour la raison du point 2.3.
  Les mesures du 24 novembre montrent sept scénarios joués en réel avec un 7B en Q4 sur cette carte, dont
  cinq du premier coup.
- **Que 32 Go suffisent à tout.** Ils font tenir un 32B en Q4 ou un 14B en Q8 : c'est le calcul du dépôt,
  pas une mesure faite ici.

## 5. Ce que ça dit du matériel

C'est l'argument le plus concret du dossier, et il est négatif : sur cette machine, **le plancher pratique
d'un agent qui boucle se situe au-dessus de ce que 3 Go peuvent charger entièrement**. En dessous, le
modèle répond mais ne chaîne pas ses outils.

| VRAM | Ce qui tient entièrement | Ce que ça change |
| --- | --- | --- |
| 3 Go (GTX 1060, machine actuelle) | 1,5B à 3B en Q4 | répond, mais ne boucle pas seul : il faut le 7B en débordement CPU, lent |
| 8 Go | 7B en Q8, 14B en Q4 | un modèle qui enchaîne, sans débordement |
| 16 Go | 14B en Q8, 32B en Q4 | un agent qui boucle confortablement, contexte large |
| 32 Go | 32B en Q6, contexte 32 k | le même agent, sans arbitrage sur la taille du modèle |

Ce n'est pas une préférence, c'est la différence entre un agent qui liste un dossier quatre fois et un
agent qui écrit le briefing.

---

*Les journaux des quatre runs sont dans [`docs/runs/live-gtx1060/`](runs/live-gtx1060/). Les deux runs
cloud ont été lancés depuis la même machine, avec les clés d'API standard, sans modification du code.*
