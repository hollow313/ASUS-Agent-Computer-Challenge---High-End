# Vigie, pour un jury qui a vingt minutes

**Le problème.** Un agent local sert à faire un travail de plusieurs étapes sans envoyer les données
ailleurs, et à le refaire demain sans qu'on le surveille. Sur une carte de 3 Go, la difficulté n'est pas
d'écrire une boucle : c'est de la rendre vérifiable, reprenable et honnête sur ce qu'elle ne sait pas.

**Ce que fait Vigie.** Il reçoit une consigne, choisit ses outils, écrit un fichier, le relit, apprend de
ses erreurs et reprend après un arrêt brutal. Neuf scénarios rejouables hors ligne, une consigne libre en
texte, la lecture d'images, et une veille quotidienne sur trois sources réelles dont chaque exécution est
versionnée dans `docs/runs/`.

**La commande qui le prouve**, sans clé, sans réseau, en trois secondes :

```bash
git clone https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End && cd ASUS-Agent-Computer-Challenge---High-End
make jury-check
```

Elle enchaîne les 89 tests, les neuf scénarios, la validation des cassettes contre les outils réels, le
diagnostic d'installation et le dimensionnement mémoire, puis écrit son récapitulatif dans
[`docs/JURY-CHECK.md`](docs/JURY-CHECK.md). Le détail de ce qui est démontré est dans
[`docs/SCENARIOS.md`](docs/SCENARIOS.md), les mesures datées dans [`docs/mesures/`](docs/mesures) et les
runs réels dans [`docs/runs/`](docs/runs).

**Ce qui est démontré.** Les tests et les scénarios rejoués par `make jury-check`. Un run live court et
reproductible : [`docs/runs/live-pico/`](docs/runs/live-pico/README.md), et le même chemin **sans carte graphique**, sur un modèle de
3 milliards, publié avec ses échecs : [`docs/runs/live-pico-cpu/`](docs/runs/live-pico-cpu/README.md). Une vision
notée sans tolérance, recalculable avec `python3 scripts/vision_check.py` qui sort dix réponses exactes sur
dix. Une veille réelle, datée, avec ses échecs : [`docs/production/journal.md`](docs/production/journal.md).

**Ce qui n'est pas démontré.** La qualité du raisonnement dépend du modèle installé à côté : 60 % de
réussite sur un 7B en Q4 sur cette carte, 90 % sur le modèle vision, et ces chiffres ne disent rien d'un
modèle de 32 milliards, que je n'ai pas pu mesurer faute de carte. Les paliers 8, 16 et 32 Go sont calculés
par `python3 -m agentdemo fit`, pas mesurés : [`docs/MATERIEL.md`](docs/MATERIEL.md).

**Le palier visé est High-End**, catégorie carte 32 Go. Ce que la carte change : un modèle de 32 milliards
en 4 bits tient en mémoire (30,4 Go de poids, 1,6 Go de marge), et avec lui la revue par un second modèle et
les sous-agents en parallèle deviennent la norme au lieu d'un réglage.

Dernier point, dit franchement : l'agent ne contient aucun modèle, c'est un choix. Une commande suffit pour
brancher Ollama, LM Studio, vLLM ou une API distante, sans reconstruction d'image.
