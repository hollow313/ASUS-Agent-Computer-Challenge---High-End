# Mesures, agent local vs cloud

Généré le 2026-11-24 16:09 UTC · 10 tâches · 1 passe(s) · notation par correspondance exacte.

## Résultats

| Cible | Type | Modèle | Réussite | p50 | p95 | tokens/s | Coût / 1 000 tâches |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vl-local | local | `qwen/qwen3-vl-8b` | 100 % | 0.94 s | 6.96 s | 2.4 | 0 € (local) |

## Méthode

- mêmes 10 tâches, même prompt système, température 0, un appel par tâche ;
- notation **déterministe** : la réponse doit contenir toutes les chaînes attendues
  (`bench/tasks.jsonl`), pas d'appréciation humaine ;
- latence mesurée côté client (aller-retour complet), p50/p95 sur tous les échantillons ;
- coût = tokens réellement rapportés par l'endpoint × prix au million
  (`bench/prices.json`), ramené à 1 000 exécutions de la tâche.

## Ce que ces chiffres ne disent pas

- pas de mesure de qualité sur des tâches longues ou ambiguës : le jeu est volontairement
  vérifiable, donc conservateur ;
- les endpoints distants varient avec la charge réseau : refaire la mesure pour un chiffre
  défendable ;
- le coût « local » ne compte que l'électricité et le matériel, pas l'amortissement du GPU.

## Détail par tâche

| Cible | Tâche | Résultat | Latence (s) | Tokens in | Tokens out |
| --- | --- | --- | --- | --- | --- |
| vl-local | cap-cartes | ok | 6.96 | 674 | 2 |
| vl-local | cap-jour | ok | 0.94 | 677 | 3 |
| vl-local | cap-lignes | ok | 0.84 | 684 | 2 |
| vl-local | cap-bouton | ok | 0.95 | 677 | 3 |
| vl-local | cap-badge | ok | 0.93 | 680 | 3 |
| vl-local | cap-titre | ok | 1.25 | 672 | 6 |
| vl-local | cap-volume | ok | 1.16 | 674 | 5 |
| vl-local | cap-boutons | ok | 0.83 | 674 | 2 |
| vl-local | cap-incident | ok | 1.76 | 678 | 11 |
| vl-local | cap-serveurs | ok | 0.84 | 671 | 2 |
