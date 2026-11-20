# Ajouter un scénario

Un scénario = un dossier dans `agentdemo/scenarios/`, quatre choses et rien d'autre :

```
agentdemo/scenarios/<slug>/
├── scenario.json # métadonnées : titre, objectif, budget d'étapes, tags
├── cassette.json # la trace de décisions (passe 1)
├── cassette2.json # optionnel : passe 2, si le scénario doit montrer un apprentissage
└── fixtures/ # les données d'entrée, copiées dans le bac à sable à chaque run
```

## 1. Échafauder

```bash
python3 -m agentdemo new --slug tri-factures \
  --title "Tri de factures" \
  --objective "Classe les factures du dossier inbox et écris rapport.md avec les montants dus."
```

Le générateur crée le dossier, un `scenario.json` pré-rempli, une cassette avec une étape
`fs_list` et une étape `final`, et un fichier d'exemple dans `fixtures/`.

## 2. Décrire l'objectif

`scenario.json` :

| Champ | Rôle |
| --- | --- |
| `slug` | identifiant, = nom du dossier |
| `title` | titre affiché dans l'interface |
| `blurb` | une phrase, visible sur la carte du scénario |
| `objective` | la consigne complète envoyée à l'agent, nomme le livrable attendu |
| `max_steps` | budget d'étapes ; dépassement → statut `budget`, jamais de boucle infinie |
| `tags` | 2-3 étiquettes techniques affichées sous le titre |
| `passes` | optionnel : liste `{"label": ... "cassette": ...}` pour un scénario en deux passes |

## 3. Écrire la cassette

Une liste JSON, **une action par entrée**, terminée par une conclusion :

```json
{"thought": "Je liste d'abord pour connaître les noms réels.", "tool": "fs_list", "args": {"path": "inbox"}}
{"thought": "J'écris le rapport.", "tool": "fs_write", "args": {"path": "rapport.md", "content": "…"}}
{"thought": "Livrable relu et vérifié.", "final": "rapport.md écrit avec 5 factures classées."}
```

Règles qui évitent les mauvaises surprises :

- **les clés d'`args` doivent correspondre exactement à la signature de l'outil** :
  `fs_move(src, dst)` et non `fs_move(path, dst)`. Une clé fausse produit une étape en erreur,
  donc une démo qui ressemble à un journal de pannes ;
- `thought` n'est pas décoratif : c'est ce que lit le jury. Écris pourquoi tu choisis l'outil,
  pas ce que tu vas faire ;
- les outils s'exécutent réellement : ne mets dans `content` que ce que tu veux vraiment voir
  sur le disque, et relis le livrable dans une étape `fs_read` avant de conclure ;
- aucune donnée réelle dans `fixtures/` : uniquement du synthétique.

## 4. Vérifier avant de pousser

```bash
python3 -m agentdemo validate # toutes les cassettes
python3 -m agentdemo validate --slug tri-factures
python3 -m agentdemo run --scenario tri-factures
```

`validate` compare chaque étape aux outils réels : nom d'outil inconnu, argument manquant ou
argument superflu, cassette vide, absence de conclusion. C'est le filet qui empêche un scénario
de pourrir silencieusement.

Ajoute ensuite le slug à la boucle du job CI `test` (`.github/workflows/docker-build.yml`) pour
qu'il soit exercé à chaque push.

## 5. Deux passes, pour montrer un apprentissage

Sur le modèle de `self-repair` : `cassette.json` contient la passe naïve (qui se casse et écrit
une procédure via `skill_write`), `cassette2.json` la passe qui commence par `skill_recall` et va
plus vite. Dans `scenario.json` :

```json
"passes": [
  {"label": "passe 1, sans procédure", "cassette": "cassette.json"},
  {"label": "passe 2, avec la procédure apprise", "cassette": "cassette2.json"}
]
```

L'interface affiche les deux passes séparées et le comparatif (étapes, erreurs).

## Sous-agents (délégation)

Un scénario peut convoquer des sous-agents. Chaque sous-agent a sa cassette dans
`children/<nom>.json`, son répertoire (`delegations/<nom>/`) et son budget :

```json
{"thought": "Trois zones indépendantes, je délègue.", "tool": "spawn_agent",
 "args": {"objective": "Analyse la zone nord", "source": "nord", "max_steps": 6}}
```

Le parent reçoit un résumé et doit relire les livrables avant d'agréger. Exemple complet dans
`scenarios/delegation/`.

## Modifier les fixtures entre deux passes

Pour démontrer qu'une procédure peut devenir fausse, une passe peut renommer un fichier avant de
démarrer :

```json
{"label": "passe 3, procédure devenue fausse", "cassette": "cassette3.json",
 "mutate": {"move": [["feeds/flux-avis-112026.xml", "feeds/flux-avis-2027.xml"]]}}
```

Le contrat `path_exists` de la procédure casse, elle est retirée, l'agent réexplore et la remplace.
C'est ce que fait `self-repair`.

## Combien de scénarios ?

Quatre suffisent. Un catalogue de dix scénarios dilue le propos : un jury retient la profondeur
d'un cas réussi, pas la longueur d'une liste. Un nouveau scénario se justifie s'il couvre une
famille d'usage absente (ici : synthèse, tri, données, apprentissage).
