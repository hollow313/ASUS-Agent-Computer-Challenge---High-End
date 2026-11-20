# Vigie — parcours de 3 minutes pour l'évaluateur

Aucune installation n'est nécessaire pour les deux premières étapes si vous partez de l'image
publiée. Tout est en français, aucune clé n'est demandée.

## 1. Lancer (30 s)

```bash
# image Docker Hub
docker run --rm -p 8080:8080 holloow313/asus-agent-computer-challenge-high-end:latest

# même image sur GHCR
docker run --rm -p 8080:8080 ghcr.io/hollow313/asus-agent-computer-challenge-high-end:latest

# avec persistance des runs (UID 568 = applications NAS)
docker run --rm -p 8080:8080 -v "$PWD/data:/data" holloow313/asus-agent-computer-challenge-high-end:latest
```

Le conteneur tourne en UID/GID 568 et n'a besoin que d'un dossier monté : `/data`. Sans montage,
Docker crée un volume anonyme et tout fonctionne quand même.

Ou sans Docker : `python3 -m agentdemo serve --port 8080` (Python 3.10+, zéro dépendance).

## 2. Voir la boucle (45 s)

Ouvrir `http://localhost:8080`, choisir **Veille cyber → briefing daté**, cliquer
**Lancer l'agent**. Cinq étapes : inventaire, parsing des trois flux, rédaction, **relecture du
fichier écrit**, conclusion. Le lien `briefing.md` en bas ouvre le livrable réel.

Ce qu'il faut regarder : l'agent se relit avant de conclure, et chaque étape est dépliable
(`arguments`, `observation`) — c'est le journal du run, pas une animation.

## 3. Voir l'agent apprendre (45 s)

Choisir **Auto-réparation → procédure apprise**, relancer. Le run se déroule en **deux passes
affichées l'une sous l'autre** :

- passe 1 : 6 étapes, **1 erreur** (nom de fichier deviné), l'agent écrit la leçon ;
- passe 2 : 4 étapes, **0 erreur** — il relit sa procédure avant d'agir.

Le bloc « bilan » affiche le comparatif. C'est le cœur de la candidature : la mémoire
procédurale, pas un prompt plus long.

## 4. Vérifier que ce n'est pas du théâtre (60 s)

```bash
python3 -m unittest discover -s tests -v     # 9 tests
python3 -m agentdemo run --scenario self-repair
python3 -m agentdemo run --scenario dataset-report --live \
  --model qwen2.5-coder:7b                   # avec un Ollama local
```

Les livrables sont écrits sur disque dans `data/runs/<run_id>/workspace/`, et le journal complet
en JSON dans `data/runs/<run_id>.json`.

## Ce que le mode replay veut dire, honnêtement

En replay, les **décisions** sont rejouées depuis une cassette (`scenarios/*/cassette.json`) :
aucun modèle n'est appelé, donc le résultat est déterministe et testable en CI. Les **outils**,
eux, s'exécutent vraiment : les fichiers sont réellement écrits, lus, déplacés, le graphique est
réellement calculé. Le mode `live` fait tourner la même boucle avec un vrai modèle, local de
préférence.
