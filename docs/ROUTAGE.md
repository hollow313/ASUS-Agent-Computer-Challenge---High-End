# Routage des modèles

La politique de routage répond à une question simple : **quel modèle traite quelle tâche**, et
pourquoi. Elle est stockée dans `data/routing.json`, se règle depuis la page `/routing`, se lit en
ligne de commande, et chaque exécution réelle est journalisée avec la décision prise.

## Ouvrir la page de configuration

```bash
python3 -m agentdemo serve --port 8080
# → http://localhost:8080/routing
```

Quatre sections : **cibles**, **règles**, **forçage manuel**, **test de décision**. Toute
modification est validée par le serveur : identifiant invalide, URL non http(s), cible absente,
expression régulière cassée ou politique sans cible sont refusés avec un message.

## Les cibles

Autant que tu veux, du moment que chaque identifiant est unique. Rien n'impose un local et un
cloud : deux instances LM Studio, deux clouds, ou un mélange.

```json
{"id": "lm-7b",  "label": "LM Studio 7B",  "base_url": "http://IP:1234/v1", "model": "qwen2.5-coder-7b-instruct", "kind": "local"}
{"id": "lm-32b", "label": "LM Studio 32B", "base_url": "http://IP:1234/v1", "model": "qwen2.5-coder-32b", "kind": "local"}
{"id": "gem",    "label": "Gemini Flash",  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.8-flash", "kind": "cloud"}
```

Le bouton **tester** interroge `/models` sur la cible et renvoie la liste des modèles chargés.

## Les règles

Elles s'évaluent **dans l'ordre du fichier**, la première qui matche gagne. Quatre types :

| Type | Ce qu'il regarde | Exemple |
| --- | --- | --- |
| `sensitive` | présence d'un mot sensible dans l'objectif | `client`, `personnel`, `confidentiel` (liste modifiable) |
| `scenario` | le slug du scénario lancé | `dataset-report` |
| `keyword` | expression régulière dans l'objectif, insensible à la casse | `r[ée]sum|tri|classement` |
| `always` | attrape tout | garde-fou en fin de liste |

Une règle `always` en première position rend les suivantes inutiles : la page le signale.

## Le forçage manuel

`override` impose une cible à toutes les exécutions réelles, quelles que soient les règles. La
page affiche un bandeau, et le bouton **lever le forçage** le désactive en un clic. C'est ce qu'on
veut pour comparer deux modèles sur la même tâche pendant une démonstration.

Le test de décision affiche alors **les deux** : la cible forcée, et celle que la politique aurait
choisie. Une décision forcée n'est pas muette, elle est explicable.

## En ligne de commande

```bash
python3 -m agentdemo route --objective "Résume le dossier client"
python3 -m agentdemo route --objective "Analyse ce jeu de données" --scenario dataset-report
python3 -m agentdemo route --override lm-32b     # force
python3 -m agentdemo route --override none       # lève le forçage
python3 -m agentdemo route                       # affiche la politique complète
```

## Comment une exécution l'utilise

En mode réel, si aucune cible n'est fournie dans la requête, le serveur résout la politique,
journalise la décision (cible, modèle, raison, règle appliquée) et lance le run avec cette cible.
La décision apparaît dans l'état du run, dans la barre de statut de l'interface, et dans
l'historique de la page de routage.

```bash
curl -s -X POST localhost:8080/api/run -H 'Content-Type: application/json' \
  -d '{"scenario":"cyber-brief","mode":"live","objective":"Résume le dossier client"}'
```

Un endpoint explicite reste prioritaire : si tu passes `llm.base_url` et `llm.model`, le routage
n'est pas consulté. C'est le comportement voulu pour un test ciblé.

## API

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/api/routing` | GET | politique complète |
| `/api/routing` | POST | enregistre une politique (validation stricte) |
| `/api/routing/decide` | POST | décision pour un objectif, avec la version sans forçage |
| `/api/routing/probe` | POST | interroge `/models` d'une cible |

## Ce que cette politique n'est pas

Ce n'est pas un routeur appris : les règles sont écrites à la main, et une règle fausse se voit
immédiatement dans l'historique. Le jour où je mesure le coût réel par type de tâche, ces règles
deviendront des seuils calculés plutôt que des intentions.

## Modèles qui voient

Un scénario peut déclarer une image (`vision`). Elle est envoyée dans le message d'ouverture sous la
forme standard, celle qu'acceptent LM Studio et Ollama :

```json
{"role": "user", "content": [
  {"type": "text", "text": "Objectif : ..."},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
]}
```

Certains serveurs compatibles refusent le champ `image_url` : l'erreur renvoyée nomme alors le champ, et
il faut soit charger un modèle vision, soit retirer le bloc `vision` du scénario. Le repli ne s'applique
pas à ce cas : une image refusée n'est pas une panne de transport.
