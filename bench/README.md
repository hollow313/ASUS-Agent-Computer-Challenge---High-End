# Banc de mesure, agent local vs cloud

Le but n'est pas de savoir « quel modèle est le meilleur », mais **ce que ça coûte et ce que ça
donne** de faire tourner l'agent sur ta machine plutôt que sur une API. Trois chiffres, tous
vérifiables :

| Chiffre | Comment il est obtenu |
| --- | --- |
| **réussite** | 10 tâches réelles de l'agent (extraction, classement, calcul), notées par **correspondance exacte**, pas d'appréciation |
| **latence** | mesure client aller-retour, p50 et p95 par tâche |
| **coût** | tokens réellement rapportés par l'endpoint × prix au million (`prices.json`), ramené à 1 000 exécutions |

Aucune dépendance : bibliothèque standard + un endpoint compatible OpenAI (Ollama, LM Studio,
vLLM, ou une API distante).

## Lancer une mesure

### 1. Un modèle local (Ollama)

```bash
ollama pull qwen2.5-coder:7b
python3 bench/bench.py --target "ollama-local=http://localhost:11434/v1|qwen2.5-coder:7b"
```

LM Studio : `--target "lmstudio=http://IP-DE-LA-MACHINE:1234/v1|llama-3.1-8b"`.

### 2. Comparer local et cloud dans le même run

```bash
python3 bench/bench.py \
  --target "ollama-local=http://localhost:11434/v1|qwen2.5-coder:7b" \
  --target "cloud=https://api.fournisseur.tld/v1|gpt-4o-mini|$CLE_API"
```

Le troisième champ de la cible est la clé API, préfère une variable d'environnement, jamais une
clé en dur dans la commande ou dans un fichier versionné.

### 3. Ou via un fichier de cibles

```bash
cp bench/targets.example.json bench/targets.json   # fichier ignoré par git
$EDITOR bench/targets.json
python3 bench/bench.py --targets bench/targets.json --repeat 3
```

## Ce qui est produit

```
bench/reports/mesures-<horodatage>.md   # rapport lisible, tableaux + méthode + limites
bench/reports/mesures-<horodatage>.json # données brutes, un échantillon par tâche
bench/reports/latence-<horodatage>.svg  # latence p50 par cible
```

Le rapport contient aussi une section honnête « ce que ces chiffres ne disent pas » : jeu de
tâches volontairement vérifiable donc conservateur, variabilité réseau des endpoints distants,
coût local qui ne compte que l'électricité et pas l'amortissement du GPU.

## Tester le banc sans modèle

Un endpoint simulé est fourni : il répond de façon déterministe, avec latence et tokens
configurables. Il valide le câblage, **il ne mesure rien**.

```bash
python3 bench/fake_endpoint.py --port 8077 &
python3 bench/bench.py --target "simule=http://127.0.0.1:8077/v1|modele-simule-8b"
```

C'est ce que fait le job CI `bench` : il vérifie que le rapport est généré et que les coûts sont
calculés, sans GPU ni clé.

## Ajouter une tâche

Une ligne JSON dans `tasks.jsonl` :

```json
{"id": "ma-tache", "prompt": "…question…", "expect": ["valeur attendue", "autre chaîne"]}
```

La notation est volontairement bête : la réponse doit contenir **toutes** les chaînes `expect`
(après normalisation : minuscules, espaces et symboles retirés). Pas de juge automatique, pas de
score inventé.
