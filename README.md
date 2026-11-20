# Vigie

### L'agent qui prend le quart : il agit, il vérifie, il apprend de ses erreurs.

[![build](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End/actions/workflows/docker-build.yml/badge.svg)](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End/actions/workflows/docker-build.yml)
![python](https://img.shields.io/badge/python-3.10%2B-3b7ddd)
![dépendances](https://img.shields.io/badge/d%C3%A9pendances-0-2ea043)
![tests](https://img.shields.io/badge/tests-32%20passent-2ea043)
![licence](https://img.shields.io/badge/licence-MIT-6e7681)

**Français** · [English](README.en.md)

Candidature à l'ASUS Agent Computer Challenge, catégorie **High-End**.

---

# Partie 1. Le projet, et pourquoi il lui manque de la puissance

Un agent, ce n'est pas un chat qui répond. C'est un programme qui reçoit un objectif, choisit des
outils, agit sur de vrais fichiers, relit ce qu'il a produit et recommence quand ça casse. La
différence entre une démonstration et un outil, c'est que la démonstration a l'air de marcher.

**Vigie** est un agent complet, exécutable en une commande, sans clé, sans réseau, sans GPU. Il
écrit des livrables réels : un briefing daté, une synthèse chiffrée avec son graphique, un tri de
boîte mail. Il apprend des procédures et les relit au run suivant. Il délègue à des sous-agents qui
ont leur propre budget. Il choisit son modèle selon la tâche. Il tourne tous les matins à 8h si on
le lui demande.

Tout cela, il le fait aujourd'hui sur une carte de 3 Go de VRAM et un modèle de 7 milliards de
paramètres. C'est là que le projet rencontre sa limite, et c'est là que la Radeon AI PRO R9700
change la nature du travail.

## Ce qui manque, et ce que la carte débloque

Avec 3 Go de VRAM, le plus gros modèle qui tourne fait 7 milliards de paramètres en 4 bits. Il est
rapide, il est gratuit, et il se trompe une fois sur deux. Le modèle qui comprend les tâches
ambiguës ne rentre pas. Les sous-agents ne peuvent pas travailler en parallèle. Le contexte reste
court, donc l'agent oublie le début du dossier au milieu du dossier.

32 Go de VRAM, ce n'est pas du confort. C'est la taille qui fait tenir un modèle de 32 milliards de
paramètres en quantification 4 bits (30,4 Go mesurés, 1,6 Go de marge pour le contexte et les
sous-agents), ou un 14 milliards en 8 bits avec 11 Go de marge. Un tel modèle lit un dossier
entier, tient un raisonnement sur trente étapes, et n'a plus besoin qu'on lui découpe le travail en
morceaux de peur qu'il perde le fil.

La mesure est dans ce dépôt, reproductible en une commande, et les limites sont écrites noir sur
blanc en partie 2. Personne n'a besoin de me croire sur parole : il suffit de lancer le banc.

## En trente secondes

```bash
git clone https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End
cd ASUS-Agent-Computer-Challenge---High-End
python3 -m agentdemo scenarios                  # les cinq scénarios, sans rien installer
python3 -m agentdemo run --scenario cyber-brief # un run complet, déterministe
python3 -m agentdemo serve --port 8080          # la même chose avec l'interface
python3 -m unittest discover -s tests           # 32 tests, un quart de seconde
```

Ou en conteneur, avec l'image utilisée pour toutes les captures de ce dépôt :

```bash
docker run --rm -p 8080:8080 holloow313/asus-agent-computer-challenge-high-end:latest
```

Aucune dépendance Python, aucun framework, aucune clé API. Le mode replay rejoue des décisions
enregistrées, mais les outils s'exécutent pour de vrai : les fichiers sont écrits, le CSV est
calculé, le graphique est généré.

![Interface](docs/screenshot-run.png)

## Les chiffres

Mêmes 10 tâches, même prompt, température 0, notation déterministe par correspondance exacte. Ce
n'est pas une appréciation, c'est un test qui passe ou qui ne passe pas. Matériel : la carte 3 Go de
VRAM qui tourne aujourd'hui dans ma machine.

| Cible | Où | Réussite | p50 | p95 | Coût / 1 000 tâches |
| --- | --- | --- | --- | --- | --- |
| Qwen 2.5 Coder 7B, Q4 | local, 3 Go de VRAM | 60 % | 0,40 s | 0,64 s | 0 € |
| Qwen3 VL 8B, Q4 | local, 3 Go de VRAM | 90 % | 11,6 s | 28,7 s | 0 € |
| DeepSeek Chat | cloud | 100 % | 0,93 s | 1,25 s | 0,02 € |

Mesure du 20/11/2026 15:39 UTC, dix tâches, une passe. Rapport brut et JSON :
[`docs/mesures/mesures-20261120.md`](docs/mesures/mesures-20261120.md).

Trois lignes, une conclusion : le local est gratuit mais se trompe une fois sur deux ou coûte trente
fois plus de temps, le cloud est juste mais sort vos données, et le modèle intermédiaire qui ferait
les deux n'existe pas dans 3 Go. C'est exactement le trou que la carte comble.

Méthode, tâches, prix et fichiers bruts : [`bench/README.md`](bench/README.md) et
[`docs/comparatif-local-cloud.md`](docs/comparatif-local-cloud.md).

## Pourquoi 32 Go, calculé et pas souhaité

```
$ python3 -m agentdemo fit --vram 32 --context 32768

modèle                     taille        quant   mémoire    marge
qwen2.5-coder-7b            7.6 B           Q8    11.7 Go   20.3 Go
qwen2.5-coder-14b          14.7 B           Q8    20.9 Go   11.1 Go
mistral-small-24b          23.6 B           Q6    26.9 Go    5.1 Go
qwen2.5-coder-32b          32.8 B           Q4    30.4 Go    1.6 Go
llama-3.3-70b              70.6 B ne rentre pas    56.0 Go  -24.0 Go
```

Un 32 milliards de paramètres en 4 bits tient, avec 1,6 Go pour le contexte long et les sous-agents.
C'est le format qui change la nature du travail : l'agent cesse de découper chaque tâche en
morceaux qu'il peut tenir, et se met à traiter le dossier entier.

La même commande sur 16 Go montre que le 32B ne rentre pas, même en Q4. La carte demandée n'est pas
un caprice, c'est un dimensionnement vérifiable.

| Aujourd'hui (3 Go) | Avec 32 Go |
| --- | --- |
| 7 à 8 B en Q4, une tâche sur deux échoue par moments | 32 B en Q4 entièrement en mémoire, 70 B possible |
| contexte court, historique tronqué | contexte long, dossier entier et raisonnement tenu |
| veille et courrier traités sur le cloud | tout reste sur la machine, données sensibles comprises |
| RAG personnel irréaliste | index sur mes archives, réponses citées |

## Ce qu'un jury peut vérifier en dix minutes

1. **Le projet tourne.** Une commande, pas de clé, cinq scénarios, des livrables écrits.
2. **Le résultat est vrai.** Le briefing, la synthèse et le graphique sont dans le bac à sable du
   run, avec un journal d'étapes horodaté et un export ZIP téléchargeable.
3. **L'agent apprend.** Relancez `self-repair` : la deuxième passe fait 4 étapes là où la première
   en faisait 6, et zéro erreur au lieu d'une. La procédure est dans `data/skills/`, lisible, avec
   son contrat de vérification.
4. **L'agent délègue vraiment.** `delegation` lance trois sous-agents qui ont chacun leur budget et
   leur dossier, puis agrège leurs livrables. Vérifié aussi en mode réel.
5. **L'agent choisit son modèle.** La page `/routing` décide quelle cible traite quelle tâche, et
   chaque exécution journalise sa décision avec sa raison.
6. **Le projet est exploitable.** `/settings` branche un dossier de CSV, une boîte IMAP et planifie
   les scénarios tous les matins. Le mot de passe n'est jamais renvoyé par l'API.
7. **Les limites sont écrites.** Partie 2 plus bas, et [`docs/PRODUCTION.md`](docs/PRODUCTION.md).

## Deux vidéos, deux choses différentes

| Vidéo | Durée | Ce qu'elle montre |
| --- | --- | --- |
| [`docs/video/agent-computer-demo.mp4`](docs/video/agent-computer-demo.mp4) | 64 s | la boucle agentique, la mémoire procédurale, les mesures |
| [`docs/video/agent-computer-delegation.mp4`](docs/video/agent-computer-delegation.mp4) | 41 s | trois sous-agents, budget cloisonné, agrégation |

La voix off de la première vidéo est produite par un outil du projet (`tts_speak`), pas par un
logiciel externe. Le fichier audio et le script de narration sont dans le dépôt.

## Trois projets, un seul concours

Ce dépôt est ma candidature à la catégorie High-End. Deux autres projets existent, sur d'autres
métiers, avec la même discipline : pas de dépendance, une démonstration qui tourne, un résultat
vérifiable.

| Niveau | Projet | Ce qu'il fait |
| --- | --- | --- |
| AI Entry | [Archiviste](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---AI-Entry) | lit un classeur administratif local, relève les échéances, répond avec sources, refuse ce qui sort du périmètre |
| Developer | [RGAA Agent](https://github.com/hollow313/ASUS-Agent-Computer-Challenge---Developer) | audite un site, corrige réellement le HTML, ré-audite : 63,9 % à 100 % de conformité sur le site de démonstration |

Le règlement n'autorise qu'une candidature par catégorie, donc je n'en présente qu'une. Les deux
autres sont publiques, exécutables, et montrent la même méthode appliquée à d'autres problèmes.

## Ce que je ne promets pas

Le coût n'est pas l'argument. À 0,05 € les mille tâches, le cloud est moins cher que l'électricité
de la carte. Une démonstration honnête ne peut pas vendre du local sur le prix.

Trois arguments tiennent la route :

- **souveraineté** : un dossier client, un courrier, une archive familiale ne sortent pas de la
  machine, et c'est vérifiable dans le code ;
- **parité de qualité en local** : 32 Go font tenir le modèle qui ne se trompe presque plus, ce que
  3 Go interdisent aujourd'hui ;
- **disponibilité** : l'agent tourne la nuit, sans quota, sans coupure, sans facture qui grimpe.

Et une suite que le matériel rend possible : un RAG sur mes archives, un affinage LoRA d'un petit
modèle sur mes propres traces, un routeur piloté par des seuils mesurés. Chaque étape produit une
mesure publiable.

---

# Partie 2. Sous le capot

## Vue d'ensemble

```
                 ┌──────────────────────────────────────────────┐
   objectif ────▶│  boucle de l'agent : plan → outil → résultat  │
                 └──────┬───────────────────────────────┬───────┘
                        │                               │
        ┌───────────────▼──────────┐        ┌───────────▼─────────────┐
        │ planner                  │        │ outils (bac à sable)    │
        │  replay : cassette       │        │  fs_*   csv_*   rss_*   │
        │  live   : /chat/...      │        │  mail_*  chart  tts     │
        └───────────────┬──────────┘        └───────────┬─────────────┘
                        │                               │
        ┌───────────────▼──────────┐        ┌───────────▼─────────────┐
        │ routage : quelle cible   │        │ mémoire procédurale     │
        │ selon la tâche           │        │ skills/, avec contrats  │
        └──────────────────────────┘        └─────────────────────────┘
```

Un seul processus, la bibliothèque standard, aucun appel réseau par défaut. Un run vit dans
`data/runs/<id>/workspace/`, écrit son journal en JSON, et laisse ses livrables sur disque.

## Le cycle de l'agent

Un tour, c'est une décision du planner et une observation. Le planner reçoit l'objectif et
l'historique, il renvoie soit un appel d'outil, soit une conclusion. Le budget d'étapes est dur :
au-delà, le run s'arrête avec le statut `budget` au lieu de boucler.

Trois garde-fous sont nés de runs réels qui déraillaient :

- **arguments tolérants** : un petit modèle renvoie parfois ses arguments en chaîne JSON, ils sont
  décodés au lieu de faire échouer l'étape ;
- **chemins suggérés** : une erreur « introuvable » renvoie le chemin réel du fichier cherché et la
  liste des CSV du run, donc le modèle se corrige au tour suivant ;
- **anti-boucle** : trois appels identiques qui échouent arrêtent le run en `blocked` au lieu de
  consommer le budget.

Ces détails ne sont pas de la finition : ce sont eux qui font la différence entre un 7B qui travaille
et un 7B qui tourne en rond.

## Replay et live, une seule interface

- **`ReplayPlanner`**, par défaut : rejoue une trace de décisions (`scenarios/<slug>/cassette.json`).
  Déterministe, hors ligne, sans clé. **Les outils s'exécutent réellement** : le bac à sable est
  vrai, les fichiers sont vrais. C'est ce qu'un juré lance en trente secondes.
- **`OpenAICompatPlanner`** : parle à tout endpoint `/chat/completions` compatible OpenAI. Le modèle
  reçoit le catalogue d'outils dans son prompt système et répond par une action JSON unique.

Un même scénario se lance donc en replay pour une démonstration et en live pour mesurer un modèle.

## Les cinq scénarios

| Scénario | Objectif donné à l'agent | Livrables réels |
| --- | --- | --- |
| `cyber-brief` | agréger trois flux, hiérarchiser, rédiger un briefing daté | `briefing.md` |
| `inbox-triage` | lire 5 messages, classer en déplaçant les fichiers, rapport d'actions | `rapport-tri.md` + `triaged/` |
| `dataset-report` | profiler un CSV, tracer un graphique, produire une note à 3 constats | `synthese.md`, `graphique.svg` |
| `delegation` | déléguer trois zones à trois sous-agents, relire, agréger | `comparatif.md` + 3 livrables |
| `self-repair` | trois passes sur le même objectif : se casser, apprendre, se corriger | `veille.md` + deux versions de la procédure |

Un scénario se crée aussi depuis l'interface (bouton **nouveau scénario**), se lance une première
fois en mode réel, puis s'enregistre comme cassette. La trace ne contient que les décisions, les
observations sont reproduites à l'exécution par les vrais outils : le replay reste honnête.

## Mémoire procédurale, et son entretien

L'agent n'est pas plus intelligent d'un run à l'autre, il est plus économe. Une procédure apprise
est un fichier JSON dans `data/skills/` avec son contenu, sa date, ses usages, un contrat de
vérification et une confiance calculée.

- `skill_recall` relit les procédures avant d'agir ;
- `skill_write` enregistre une leçon avec son contrat (« le fichier existe et a 3 colonnes ») ;
- `skill_feedback` met à jour la confiance selon le succès ou l'échec ;
- `skill_revise` réécrit une procédure périmée et ne la réactive que si le nouveau contrat passe ;
- `skill_resolve` arbitre deux procédures contradictoires par la preuve, pas par la date ;
- `maintenance_run` fait une passe d'entretien : réparer par ressemblance de nom, arbitrer, retirer.

Dans `self-repair`, la deuxième passe fait 4 étapes et 0 erreur là où la première en faisait 6 avec
une erreur. La procédure devenue fausse (le fichier est renommé entre deux passes) est détectée par
son contrat cassé, pas par la chance.

```bash
python3 -m agentdemo skills            # registre : statut, succès, usages, confiance, contrat
python3 -m agentdemo maintain --once   # réparer, arbitrer, mettre à la retraite
python3 -m agentdemo maintain --interval 300
```

![Comparatif des trois passes](docs/screenshot-selfrepair.png)

## Délégation de sous-agents

Un sous-agent n'est pas un appel de fonction. Il a son propre budget, son propre journal, son
propre bac à sable dans `delegations/<nom>/`, et le parent ne partage rien avec lui, sauf
l'inventaire des fichiers d'entrée.

Deux modes : si une cassette existe pour ce nom, le sous-agent la rejoue ; sinon, si le run parle à
un vrai modèle, il hérite de l'endpoint et du modèle du parent et travaille pour de bon. La
profondeur est bornée à trois niveaux, un sous-agent déjà lancé ne se relance pas, et un sous-agent
qui dépasse son budget rend la main avec son statut.

```
parent (8 étapes, mode réel)
├── sous-agent zone-nord  → livrable analysé
├── sous-agent zone-ouest → livrable analysé
├── sous-agent zone-sud   → livrable analysé
└── relecture des trois, puis comparatif.md
```

## Routage des modèles

Un agent qui parle à un seul modèle prend le mauvais outil pour chaque tâche. La page `/routing`
déclare autant de cibles qu'on veut (deux instances LM Studio, deux clouds, ou un mélange) et des
règles ordonnées : mots sensibles, scénario, motif dans l'objectif, garde-fou. La première règle qui
matche gagne, un forçage manuel peut tout écraser, et chaque exécution réelle journalise sa décision
avec sa raison.

![Page de routage](docs/screenshot-routing.png)

```bash
python3 -m agentdemo route --objective "Résume le dossier client"     # local, données sensibles
python3 -m agentdemo route --objective "Analyse ce jeu de données" --scenario dataset-report
python3 -m agentdemo route --override local-gros                     # force une cible
```

Détail complet : [`docs/ROUTAGE.md`](docs/ROUTAGE.md).

## Entrées réelles et planification

`/settings` déclare les vraies entrées : un dossier de CSV (copié dans `inputs/` à chaque run, jamais
monté en écriture), des flux RSS, un compte IMAP avec son dossier d'archive. Le mot de passe est
stocké en 0600 sur le volume, l'API renvoie `********` et un booléen.

![Réglages d'exploitation](docs/screenshot-settings.png)

Deux outils de courrier parlent à la boîte pour de vrai, avec `imaplib` de la bibliothèque standard :
`mail_list` lit expéditeur, objet, date et extrait ; `mail_move` archive un message. Sans compte
configuré, l'outil refuse et dit où le renseigner. Vérifié sur une vraie boîte : 18 messages lus,
rapport écrit en 5 étapes, aucun message déplacé pendant le test.

Le planificateur tourne dans le processus du serveur, relit `settings.json` à chaque tour et consomme
chaque échéance une seule fois : chaque jour à heure fixe, ou toutes les N minutes. Une tâche créée
après son heure se déclenche une fois, puis reprend son rythme : c'est le rattrapage voulu après une
coupure. Vérifié en conteneur : tâche due, déclenchée en 20 s, run produit, historique conservé.

```
08:00  veille cyber   → briefing daté        (chaque jour, heure fixe)
02:00  rapport CSV    → analyse + graphique  (toutes les 1440 minutes)
```

## Sécurité et données

- bac à sable par run : tout chemin hors du dossier, y compris par `../`, est refusé ;
- réseau coupé par défaut (`AGENTDEMO_ALLOW_NETWORK=0`), outils réseau désactivés sauf demande ;
- aucune suppression : les tris se font par déplacement, tout est réversible ;
- secrets hors du dépôt : un clone neuf ne contient aucune clé, aucune adresse, aucun chemin de
  machine, et les fichiers `settings.json` / `routing.json` vivent dans le volume ;
- conteneur non privilégié, UID 568, un seul volume `/data`, pas de socket Docker ;
- CI qui construit l'image, démarre le conteneur, appelle `/healthz`, lance un scénario et
  télécharge le livrable avant publication.

## Mesurer au lieu d'affirmer

`bench/bench.py` fait dix tâches à notation exacte sur n'importe quel endpoint compatible OpenAI,
mesure la latence côté client (p50 et p95), compte les tokens réellement rapportés et calcule un
coût pour mille exécutions.

```bash
python3 bench/bench.py --target "local=http://IP:1234/v1|modele" --repeat 3
```

Ce que ces chiffres ne disent pas, et qui figure dans le rapport généré : le jeu de tâches est court
et vérifiable, donc conservateur ; les endpoints distants varient avec la charge ; le coût local ne
compte pas l'amortissement de la carte.

## Dimensionnement mémoire

`agentdemo fit` prend une VRAM, un contexte et une liste de modèles, puis dit ce qui tient :
`poids = paramètres × octets par milliard selon la quantification + 1,5 Go de runtime`. Les
hypothèses sont dans `agentdemo/fit.py`, la table ci-dessus vient de la commande.

## Construire, lancer, tester

```bash
python3 -m agentdemo doctor                    # diagnostic avant de lancer
python3 -m agentdemo run --scenario delegation # replay, déterministe
python3 -m agentdemo serve --port 8080         # interface, /routing, /settings
python3 -m agentdemo export                    # archive du dernier run
python3 -m agentdemo route --objective "..."   # décision de routage
python3 -m agentdemo fit --vram 32             # dimensionnement
python3 -m agentdemo validate                  # cohérence des cassettes avec les outils
python3 -m unittest discover -s tests          # 32 tests
```

En conteneur, l'UID 568 doit posséder le volume :

```bash
mkdir -p /mnt/<pool>/apps/agent-demo && chown -R 568:568 /mnt/<pool>/apps/agent-demo
docker run -d --name agentdemo -p 8080:8080 \
  -v /mnt/<pool>/apps/agent-demo:/data \
  holloow313/asus-agent-computer-challenge-high-end:latest
```

Deux registres : `holloow313/...` sur Docker Hub (tirage sans authentification) et
`ghcr.io/hollow313/...` sur GHCR. Tags `latest`, `sha-*` et `v*`.

### Brancher un vrai modèle

Le mode réel pointe vers tout endpoint compatible OpenAI : LM Studio, Ollama, vLLM, ou une API
distante. Trois champs dans l'interface (endpoint, modèle, clé optionnelle), un bouton qui interroge
`/models` et remplit la liste, quatre préréglages fournis.

```bash
python3 -m agentdemo run --scenario cyber-brief --live \
  --base-url http://MON-IP:1234/v1 --model llama-3.1-8b
```

En variables d'environnement, pratique dans un conteneur : `AGENTDEMO_LLM_BASE_URL`,
`AGENTDEMO_LLM_MODEL`, `AGENTDEMO_LLM_API_KEY`. Le suffixe `/v1` est ajouté s'il manque, et
l'erreur est expliquée au lieu de renvoyer un code brut.

![Panneau du modèle live](docs/screenshot-live.png)

## API

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/` | GET | interface web |
| `/healthz` | GET | sonde de santé |
| `/api/scenarios` | GET, POST | liste des scénarios, ou en crée un |
| `/api/scenarios/<slug>/record` | POST | enregistre la trace d'un run comme cassette |
| `/api/run` | POST | `{"scenario": "...", "mode": "replay\|live", "llm": {...}}` |
| `/api/runs/<id>` | GET | état, étapes, bilan, livrables |
| `/api/runs/<id>/export` | GET | archive du run : journal et livrables |
| `/api/artifacts/<id>/<chemin>` | GET | téléchargement d'un livrable |
| `/api/skills` | GET | procédures apprises, confiance et statut |
| `/api/maintenance` | GET | dernières passes d'entretien |
| `/api/maintenance/run` | POST | déclenche une passe d'entretien |
| `/api/routing` | GET, POST | politique de routage |
| `/api/routing/decide` | POST | décision pour un objectif |
| `/api/routing/probe` | POST | interroge `/models` d'une cible |
| `/api/settings` | GET, POST | entrées réelles et planning |
| `/api/settings/test-mail` | POST | teste la connexion IMAP |
| `/api/jobs/<id>/run` | POST | lance une tâche planifiée maintenant |
| `/api/llm/models` | GET | sonde un endpoint compatible OpenAI |

## Limites assumées

- **Pas d'affinage.** L'agent n'apprend pas de nouveaux poids, il accumule des procédures écrites.
  Un modèle affiné serait meilleur, ce n'est pas ce que fait ce dépôt.
- **Pas de réécriture automatique du contenu.** Une procédure fausse est détectée par son contrat
  cassé et mise à la retraite, mais son texte n'est pas réécrit par le modèle pendant l'entretien.
- **Planificateur simple.** Une instance, pas de verrou distribué, une seule échéance rattrapée.
  Pour plusieurs instances, il faut un ordonnanceur externe.
- **Réglages en un seul fichier.** Deux onglets ouverts en même temps se marchent dessus.
- **IMAP en lecture et déplacement seulement.** Pas de réponse, pas de pièces jointes traitées.
- **Le mode réel dépend du modèle.** Un 7B se trompe, se répète, invente des chemins. Les garde-fous
  amortissent, ils ne corrigent pas un modèle trop petit. C'est précisément l'argument de la carte.
- **Pas d'IMAP réel dans la CI.** Le chemin est vérifié à la main, l'automatisation couvre les cas
  d'erreur.
- **Ce n'est pas mon agent de production.** L'instance réelle tourne en permanence sur un serveur
  personnel, avec une centaine de procédures, vingt tâches planifiées, un navigateur piloté sur une
  autre machine. Elle contient des données privées, donc elle ne se publie pas. Ce dépôt est la
  version publiable, avec les mêmes mécanismes.

## Structure du dépôt

```
agentdemo/
├── agent.py              # la boucle : planification, outil, observation, bilan
├── planners.py           # replay déterministe + endpoint compatible OpenAI
├── tools.py              # outils du bac à sable, délégation, mémoire
├── skills.py             # mémoire procédurale : contrats, confiance, révision, arbitrage
├── maintenance.py        # entretien : réparer, arbitrer, retirer
├── routing.py            # politique de routage : cibles, règles, forçage, historique
├── settings_store.py     # entrées réelles et planning (mot de passe jamais renvoyé)
├── mailbox.py            # lecture et tri d'une vraie boîte IMAP (imaplib)
├── fit.py                # dimensionnement mémoire : ce qui tient dans une carte
├── doctor.py             # diagnostic d'installation
├── export.py             # archive d'un run : journal, livrables, synthèse
├── scenarios_loader.py   # chargement des scénarios, cassettes et fixtures
├── cli.py                # CLI : run, serve, doctor, export, fit, skills, maintain, validate, new
├── server.py             # API HTTP, interface web et planificateur (http.server)
├── web/index.html        # interface d'une page, aucune dépendance
├── web/routing.html      # page de configuration du routage
├── web/settings.html     # page d'exploitation : entrées, IMAP, planning
└── scenarios/            # cyber-brief, inbox-triage, dataset-report, delegation, self-repair
tests/test_demo.py        # 32 tests : scénarios, procédures, délégation, bac à sable
bench/                    # banc de mesure : tâches, prix, endpoint simulé
video/                    # cartons, capture d'interface et script de narration
docs/                     # captures, architecture, comparatif, scénarios, parcours 3 min
```

## Ajouter un scénario

```bash
python3 -m agentdemo new --slug tri-factures --title "Tri de factures" \
  --objective "Classe les factures du dossier inbox et écris rapport.md."
python3 -m agentdemo validate --slug tri-factures
python3 -m agentdemo run --scenario tri-factures
```

Un scénario, c'est un dossier avec `scenario.json`, `cassette.json` (une action par étape, clés
d'`args` strictement conformes à la signature de l'outil) et `fixtures/`. `validate` compare les
cassettes aux outils réels : outil inconnu, argument manquant ou superflu, absence de conclusion.
Format complet : [`docs/SCENARIOS.md`](docs/SCENARIOS.md). Parcours de trois minutes pour un
évaluateur pressé : [`docs/DEMO.md`](docs/DEMO.md).

## Licence et auteur

MIT, voir `LICENSE`. Auteur : Loïc Huon.
