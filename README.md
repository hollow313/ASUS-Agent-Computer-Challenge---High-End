# Agent Computer — démo agentique exécutable

**Candidature ASUS Agent Computer Challenge — catégorie High-End**

Une démo volontairement petite, mais honnête : un agent qui reçoit un objectif, choisit des
outils, enchaîne les étapes, **vérifie ce qu'il a produit** et rend un livrable sur le disque.
Aucune clé API, aucun réseau, aucune dépendance : deux commandes et ça tourne.

![Interface de la démo](docs/screenshot-run.png)

---

## 1. Ce que cette démo prouve

Ce dépôt est la version **exécutable et nettoyée** du système décrit dans ma candidature. Il
n'embarque pas mon instance de production (elle contient des données personnelles et des
identifiants), il embarque **la boucle** :

```
objectif  →  planification  →  appel d'outil  →  observation  →  …  →  vérification  →  livrable
                    ↑                                                      │
                    └──────────────────  journal du run  ──────────────────┘
```

Trois choses sont réelles ici, et c'est ce qui distingue un agent d'un chatbot :

1. **Les décisions sont séquencées par le système, pas par l'utilisateur.** L'agent enchaîne
   seul les étapes, avec un budget maximal : au-delà, le run s'arrête proprement (statut
   `budget`) au lieu de boucler.
2. **Les outils ont des effets réels.** Les fichiers écrits existent, les messages déplacés le
   sont vraiment, le graphique SVG est généré à partir des données. Rien n'est une capture.
3. **La vérification fait partie de la boucle.** Dans chaque scénario, l'agent relit le fichier
   qu'il vient d'écrire avant de conclure — un livrable annoncé n'est pas un livrable.

Un journal JSON est écrit pour chaque run (`data/runs/<run_id>.json`) : objectif, chaque
pensée, chaque appel d'outil, chaque observation, la durée, le bilan. Tout est auditable.

---

## 2. Démarrage rapide

### Option A — Docker (recommandé)

```bash
# 1. image publiée automatiquement par la CI (GitHub Actions → ghcr.io)
docker run --rm -p 8080:8080 ghcr.io/hollow313/asus-agent-computer-challenge-high-end:latest

# 2. ou construite localement depuis les sources
docker compose up --build
# → http://localhost:8080
```

Ou à la main :

```bash
docker build -t agent-computer-demo .
docker run --rm -p 8080:8080 agent-computer-demo
```

### Option B — sans Docker, Python 3.10+ uniquement

```bash
python3 -m agentdemo serve --port 8080
# → http://localhost:8080
```

### Option C — en ligne de commande (sans interface web)

```bash
python3 -m agentdemo scenarios
python3 -m agentdemo run --scenario cyber-brief
python3 -m agentdemo run --scenario inbox-triage
python3 -m agentdemo run --scenario dataset-report
```

Chaque run écrit son espace de travail dans `data/runs/<run_id>/workspace/` : c'est là que se
trouvent les livrables.

> Aucune dépendance à installer. Aucun `pip install`. Le paquet n'utilise que la bibliothèque
> standard (voir `requirements.txt`, volontairement vide).

---

## 3. Les trois scénarios

| Scénario | Objectif donné à l'agent | Livrables produits |
| --- | --- | --- |
| `cyber-brief` | Agréger trois flux RSS, hiérarchiser, rédiger un briefing daté de 5 entrées | `briefing.md` |
| `inbox-triage` | Lire 5 messages, les classer en déplaçant les fichiers, rapport d'actions | `rapport-tri.md` + arborescence `triaged/` |
| `dataset-report` | Profiler un CSV, tracer un graphique, produire une note à 3 constats | `synthese.md`, `graphique.svg` |
| `self-repair` | **Deux passes sur le même objectif** : la première devine un nom de fichier et se casse, l'agent écrit la procédure, la seconde va droit au but | `veille.md` + une procédure persistée |

Ils couvrent quatre familles d'usage réel : **synthèse d'informations**, **tri / décision**,
**analyse de données**, et **apprentissage par l'erreur**. Ce sont exactement les tâches que je
délègue au quotidien.

### Le scénario `self-repair`, en une ligne

Passe 1 : 6 étapes, 1 erreur (mauvais nom de fichier deviné), et l'agent **écrit la leçon** dans
une procédure. Passe 2, même objectif : il **relit la procédure d'abord**, puis 4 étapes et
zéro erreur. C'est la seule chose de cette démo qui ne s'achète pas avec un meilleur modèle :
c'est de la mémoire procédurale, et c'est ce que fait mon agent de production à l'échelle de
~90 procédures.

---

## 4. Deux planificateurs, une seule boucle

Le cœur de l'agent (`agentdemo/agent.py`) ne sait pas d'où viennent les décisions. Deux
backends implémentent la même interface :

- **`ReplayPlanner`** (défaut) — rejoue une trace de décisions enregistrée
  (`scenarios/<slug>/cassette.json`). Déterministe, hors ligne, sans clé, sans modèle. **Les
  outils, eux, s'exécutent pour de vrai** : le bac à sable est réel, les fichiers sont réels.
  C'est le mode que le jury peut lancer en 30 secondes, sans rien installer d'autre.
- **`OpenAICompatPlanner`** — parle à n'importe quel endpoint `/chat/completions` compatible
  OpenAI : **Ollama**, **LM Studio**, vLLM, ou une API distante. Le modèle reçoit le catalogue
  d'outils dans son prompt système et doit répondre par une action JSON unique.

### Passer en mode live, 100 % local, sans clé

```bash
# 1. un modèle local (Ollama)
ollama pull qwen2.5-coder:7b

# 2. l'agent, en ligne de commande
AGENTDEMO_LLM_BASE_URL=http://localhost:11434/v1 \
AGENTDEMO_LLM_MODEL=qwen2.5-coder:7b \
python3 -m agentdemo run --scenario cyber-brief --live
```

Ou dans l'interface web : bouton **live (modèle)**, puis *Lancer l'agent*. Les variables
d'environnement sont les mêmes (`AGENTDEMO_LLM_BASE_URL`, `AGENTDEMO_LLM_MODEL`,
`AGENTDEMO_LLM_API_KEY` si l'endpoint en exige une).

C'est le point qui compte pour un Agent Computer : **la même boucle, les mêmes outils, le même
journal**, avec le calcul qui reste sur la machine et aucune donnée qui sort.

---

## 5. Les outils

Tous les outils opèrent dans un bac à sable : un répertoire par run. Un chemin absolu ou une
remontée `../` est refusé, pas « corrigé ».

| Outil | Signature | Rôle |
| --- | --- | --- |
| `fs_list` | `fs_list(path)` | inventaire d'un dossier |
| `fs_read` | `fs_read(path, max_chars?)` | lecture d'un fichier texte |
| `fs_write` | `fs_write(path, content)` | écriture d'un livrable |
| `fs_move` | `fs_move(src, dst)` | déplacement (le tri se fait par mouvement, jamais par suppression) |
| `csv_profile` | `csv_profile(path)` | agrégats d'un CSV (min/max/total/moyenne) |
| `chart_bar` | `chart_bar(path, label_column, value_column, output, title?)` | graphique SVG |
| `rss_rank` | `rss_rank(paths[], top_n?)` | parsing de flux RSS + classement |
| `http_get` | `http_get(url, max_chars?)` | GET HTTP — **désactivé par défaut** |
| `skill_recall` | `skill_recall(keyword?)` | relit une procédure apprise avant d'agir |
| `skill_write` | `skill_write(name, content)` | enregistre une procédure réutilisable |
| `skill_list` | `skill_list()` | inventaire des procédures connues |

Ce catalogue est délibérément court. Un agent se juge sur la façon dont il choisit ses outils,
pas sur le nombre d'outils qu'on lui donne.

### Mémoire procédurale

Les procédures vivent dans `data/runs/<run_id>/skills/*.md`, hors du bac à sable du run : elles
survivent donc à la fin du run, et la passe suivante les relit. Le store est recréé à chaque
nouveau run pour que la démo reste déterministe et rejouable ; en production il est global et
persiste indéfiniment.

---

## 6. Modèle de sécurité

Un agent qui exécute des actions doit être contraint. Ce que fait la démo :

- **Bac à sable par run** : chaque exécution a son répertoire, les chemins hors périmètre sont
  rejetés par `Sandbox.resolve()` (testé dans `tests/test_demo.py`).
- **Réseau coupé par défaut** : `AGENTDEMO_ALLOW_NETWORK=0`. L'outil `http_get` échoue avec un
  message explicite au lieu de simuler un succès.
- **Aucune suppression** : le tri se fait par déplacement, tout reste réversible.
- **Budget d'étapes** : `max_steps` par scénario ; le dépassement produit un statut `budget`,
  jamais une boucle infinie.
- **Journal complet** : chaque run est rejouable et vérifiable sur disque.
- **Conteneur non privilégié** : l'image tourne avec un utilisateur non-root (`uid 10001`).

Il n'y a aucun secret dans ce dépôt, aucun identifiant, aucune donnée personnelle. Les données
des scénarios sont synthétiques et vivent dans `agentdemo/scenarios/*/fixtures`.

---

## 7. Structure du dépôt

```
agentdemo/
├── agent.py              # la boucle : planification → outil → observation → bilan
├── planners.py           # ReplayPlanner (hors ligne) + OpenAICompatPlanner (modèle live)
├── tools.py              # outils + bac à sable + génération SVG
├── skills.py             # mémoire procédurale persistante
├── scenarios_loader.py   # chargement des scénarios et des fixtures
├── cli.py                # CLI : scenarios / run / serve
├── server.py             # API HTTP + interface web (http.server, stdlib)
├── web/index.html        # interface d'une page, aucune dépendance
└── scenarios/
    ├── cyber-brief/      # scenario.json + cassette.json + fixtures/
    ├── inbox-triage/
    └── dataset-report/
tests/test_demo.py        # 9 tests : scénarios, apprentissage, bac à sable, budget
docs/                     # captures d'écran et notes d'architecture
Dockerfile, docker-compose.yml, Makefile
```

### API

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/` | GET | interface web |
| `/api/scenarios` | GET | liste des scénarios |
| `/api/run` | POST | `{"scenario": "...", "mode": "replay|live", "objective": "..."}` → `{"run_id": ...}` |
| `/api/runs/<id>` | GET | état, étapes, bilan, livrables |
| `/api/artifacts/<id>/<chemin>` | GET | téléchargement d'un livrable |
| `/healthz` | GET | sonde de santé |

---

## 8. Tests

```bash
python3 -m unittest discover -s tests -v
```

9 tests, aucun framework : les scénarios vont jusqu'au bout, les livrables sont vérifiés sur le
disque, `self-repair` prouve que la passe 2 est plus courte et sans erreur, le bac à sable
refuse les évasions, le budget d'étapes est respecté, un outil inconnu produit une observation
d'erreur au lieu d'un crash.

---

## 9. Ce que la démo n'est pas

Je préfère l'écrire noir sur blanc, un jury technique le verra de toute façon :

- **Ce n'est pas mon agent de production.** L'instance réelle tourne en permanence sur un
  serveur personnel, avec ~90 procédures écrites par l'agent lui-même, 20 tâches planifiées, un
  navigateur piloté en CDP sur une autre machine, IMAP/SMTP, API de messagerie, et un routage
  entre modèles locaux et cloud. Elle contient des données privées : elle ne se publie pas.
- **Le mode replay ne raisonne pas.** Il rejoue des décisions enregistrées. C'est un choix
  assumé : une démo qui exige une clé API ou un modèle de 20 Go n'est pas une démo, c'est une
  condition d'accès. Le mode live existe pour prouver que la boucle fonctionne avec un vrai
  modèle, y compris un modèle local.
- **Le catalogue d'outils est réduit** à 11 outils, tous en lecture/écriture de fichiers et en
  analyse. Pas de shell, pas d'envoi de mail, pas d'automatisation de navigateur ici.
- **La mémoire procédurale est une version réduite** : un dossier de procédures markdown, relu
  au run suivant, mais sans déduplication, sans score de confiance et sans révision
  automatique. À l'échelle de production (~90 procédures), le vrai travail est le tri et la
  correction des procédures obsolètes ; ce dépôt n'en montre que le principe.

Ce que la démo démontre en revanche n'est pas simulé : la boucle, les outils, le bac à sable,
le journal, la vérification, l'arrêt propre en cas d'erreur ou de budget dépassé.

---

## 10. Du prototype au poste de travail

La limite actuelle de mon installation est le calcul : **3 Go de VRAM**, donc des modèles de
3-4 B en quantification agressive, et une bascule quasi systématique vers le cloud dès que la
tâche demande du raisonnement. Conséquences : coût par token, dépendance réseau, et
impossibilité de traiter en local les documents sensibles.

Un Agent Computer avec 16 Go de VRAM change la nature du système, pas seulement sa vitesse :

| Aujourd'hui (3 Go) | Avec 16 Go |
| --- | --- |
| modèles 3-4 B, contexte court | 14 B à 32 B en Q4/Q5, contexte utilisable |
| tout ce qui est sensible part au cloud | veille et tri mail traités hors ligne |
| pas de RAG personnel réaliste | index sur mes propres archives |
| coût par token sur les tâches planifiées | coût marginal = électricité |

Le plan des 30 jours après réception est dans la candidature : mesurer 14 B/32 B contre le
modèle cloud sur les mêmes tâches, basculer la veille et le tri mail en local, monter un RAG sur
mes archives, ouvrir l'agent à un second utilisateur, publier le comparatif chiffré.

---

## 11. Licence et auteur

MIT — voir `LICENSE`. Auteur : Loïc Huon.

---

## English summary

A minimal, runnable agentic loop submitted to the ASUS Agent Computer Challenge (High-End
category). An agent receives an objective, picks tools, chains steps, verifies its own output
and writes real deliverables to disk. Two planners share one loop: a deterministic offline
replay (no API key, no network, real tool execution in a per-run sandbox) and an
OpenAI-compatible live planner that works with a local model (Ollama, LM Studio, vLLM).

```bash
docker compose up --build   # http://localhost:8080
python3 -m agentdemo run --scenario cyber-brief   # no dependency, no key
python3 -m unittest discover -s tests -v          # 8 tests
```

Three scenarios: RSS → dated briefing, inbox triage → report, CSV → analysis + SVG chart.
Everything is sandboxed, logged as JSON, and safe to run.
