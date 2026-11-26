# pico sans carte graphique : ce que chaque modèle donne

Ce dossier publie les essais réels du même scénario `pico` sur un Ollama sans GPU, avec quatre modèles de
tailles différentes. Deux échouent proprement, un réussit deux fois de suite, et un sert de référence sur
carte. C'est cette page qui remplace la phrase « conçu pour un 1,5B », qui n'était pas prouvée.

## Le tableau

| Modèle | Où | Résultat | Étapes |
| --- | --- | --- | --- |
| `qwen2.5:1.5b-instruct` | NAS, CPU, sans GPU | boucle sur `fs_read`, arrêt `blocked` | 5 |
| `qwen2.5:3b-instruct` | NAS, CPU, sans GPU | même boucle, arrêt `blocked` | 5 |
| `llama3.2:3b`, message clair sans tolérance | NAS, CPU, sans GPU | arguments invalides deux fois, puis boucle, `blocked` | 7 dont 3 erreurs |
| **`llama3.2:3b`, après correctif** | **NAS, CPU, sans GPU** | **`done`, `pico.md` écrit, 3 min 14, deux essais sur deux** | 4 |
| `qwen/qwen3-vl-8b` | carte 3 Go | `done`, `pico.md` écrit | 3 |

Journaux : [`journal-llama32-3b.json`](journal-llama32-3b.json) pour le run retenu,
[`journal-llama32-3b-avant-correctif.json`](journal-llama32-3b-avant-correctif.json) pour l'échec,
[`journal.json`](journal.json) pour le 1,5B. Livrable : [`pico-llama32-3b.md`](pico-llama32-3b.md).

## Ce que l'échec a appris, et ce qui a changé

Le modèle envoyait `fs_write(path, content, max_chars)` : il recopiait un argument de `fs_read`. L'outil
refusait l'appel, le modèle recommençait, puis se rabattait sur la lecture et bouclait.

Deux corrections dans le moteur, et la deuxième a été trouvée parce que la première n'a pas suffi :

- **la première** remplace l'erreur Python par la signature attendue, `Signature attendue :
  fs_write(path, content)`. Le journal de cet essai montre que c'est nécessaire mais pas suffisant : le
  modèle refait le même appel fautif, puis retourne lire, et le run s'arrête en `blocked` avec trois
  erreurs en sept étapes ;
- **la seconde** écarte l'argument inconnu au lieu de refuser l'appel, et le nomme dans l'observation :
  `(argument ignoré : max_chars)`. C'est celle qui débloque le run.

Après les deux, deux essais consécutifs terminent en quatre étapes, 194 secondes, même livrable.

## La commande

```bash
python3 -m agentdemo run --scenario pico --live --model llama3.2:3b \
  --base-url http://192.168.1.200:30068/v1
```

## Ce que ça prouve, et ce que ça ne prouve pas

Ça prouve que la boucle complète tourne sur une machine sans carte graphique, avec un modèle de
3 milliards, en trois minutes, et que le livrable est écrit. Ça ne prouve pas la qualité : le résumé est
celui d'un 3 milliards, juste sur une note de cinq lignes, et il ne dirait rien d'un dossier de cent pages.

Ça prouve aussi, indirectement, que le garde-fou anti-boucle et la tolérance aux arguments sont nécessaires
sur les petits modèles : sans eux, le même scénario échoue. C'est mesuré, pas supposé.

Les deux `qwen2.5` de 1,5 et 3 milliards, eux, ne produisent pas d'appel d'outil fiable : ils relisent le
fichier indéfiniment et l'agent s'arrête en le disant, au lieu de tourner jusqu'au budget.
