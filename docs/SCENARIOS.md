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
| `passes` | optionnel : liste `{"label": ... "cassette": ...}` pour un scénario en plusieurs passes |

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

L'interface affiche les passes séparées et le comparatif (étapes, erreurs).

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

## `local-audit`, le scénario métier

Dossier : `agentdemo/scenarios/local-audit/`. Deux passes, comme `self-repair`, mais sur un cas
métier : journaux d'authentification, ports en écoute, configuration SSH, règle sudo.

- réseau `deny` : rien ne sort, et le rapport du run l'indique ;
- `exec` déclaré avec `allow_unsandboxed` pour `grep` et `wc` sur les fichiers du run seulement ;
- la passe 1 écrit deux procédures (`reconnaitre-bruteforce-ssh`, `port-expose-vs-necessaire`),
  la passe 2 les relit et passe de 11 à 6 étapes, zéro erreur.

## Politique réseau d'un scénario

Champ `network` du `scenario.json`, obligatoire dans les faits puisque le défaut est `deny` :

```json
"network": {"mode": "deny"}
"network": {"mode": "allowlist", "hosts": ["exemple.local"]}
"network": {"mode": "open", "justification": "pourquoi c'est nécessaire"}
```

`http_get` et `rss_rank` consultent cette politique avant tout appel. Un refus écrit
`{"event": "network_denied", "tool": ..., "url": ..., "reason": ...}` dans le journal du run.

## revue-contradictoire

Un premier jet est écrit, un relecteur le refuse (gravités absentes, conséquences non dites), le
rédacteur corrige, le relecteur accepte. Le livrable final contient les trois risques qualifiés et une
recommandation.

Ce scénario sert à montrer la revue : `reviewer.json` porte deux verdicts, rejoués dans l'ordre. Lancez
`python3 -m agentdemo run --scenario revue-contradictoire --review` et regardez deux étapes `review`
dans le journal, une rejetée puis une acceptée.

## capture-audit

Une capture d'écran entre dans le run. Le modèle local la lit, l'outil `image_probe` mesure ce que le
modèle ne sait pas compter de façon fiable (format, dimensions, poids), et le rapport cite une zone en
pixels pour chaque constat.

Le scénario déclare sa vision dans `scenario.json` :

```json
"vision": {"image": "capture.png", "max_bytes": 1500000}
```

L'image part **une seule fois**, au premier message du run, sinon les jetons d'entrée sont multipliés par
le nombre d'étapes. En replay, aucune image n'est envoyée : la cassette porte la description.

Limites assumées : images fixes seulement, 1,5 Mo maximum, pas de redimensionnement (aucune dépendance
pour le faire), PNG ou JPEG.

    python3 -m agentdemo run --scenario capture-audit
    python3 -m agentdemo run --scenario capture-audit --live --model qwen3-vl-8b --base-url http://IP:1234/v1
