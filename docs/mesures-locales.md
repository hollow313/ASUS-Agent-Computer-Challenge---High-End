> Mise à jour du 21/11/2026, 13:37 UTC : nouvelle passe complète des trois cibles sur la même
> machine. 7B : 60 %, p50 0,75 s, p95 3,98 s. 8B vision : 90 %, p50 0,67 s, p95 4,63 s. Gemini 3.8
> Flash : 100 %, p50 4,17 s, p95 5,23 s, 0,07 € les 1 000 tâches. Rapport brut :
> [`mesures/mesures-20261121.md`](mesures/mesures-20261121.md). Les tableaux ci-dessous sont la
> première passe, conservée pour montrer la variabilité entre deux exécutions.

# Mesures, modèles locaux sur la machine actuelle

Mesures réelles, exécutées le 20/11/2026 sur mon poste, GPU **3 Go de VRAM**, via LM Studio.
Aucun appel sortant : les deux modèles tournent en local, en Q4.

| Cible | Modèle | Réussite | p50 | p95 | tokens/s | Coût / 1 000 tâches |
| --- | --- | --- | --- | --- | --- | --- |
| local-7b-coder | qwen2.5-coder-7b (Q4, LM Studio) | 60 % | 0.48 s | 0.93 s | 11.6 | 0 € (local) |
| local-8b-vl | qwen3-vl-8b (Q4, LM Studio) | 90 % | 18.92 s | 38.18 s | 0.3 | 0 € (local) |

**10 tâches vérifiables** (extraction, classement, calcul, date), notation par
correspondance exacte, température 0, 1 passe(s).

## Ce que ça dit

- la vitesse et la justesse ne vont pas ensemble sur un GPU de 3 Go : le 7B répond en moins
  d'une demi-seconde mais **se trompe sur 4 tâches sur 10** (arithmétique, classification,
  réponse oui/non) ;
- le 8B vision réussit 9 tâches sur 10 mais coûte **près de quarante fois plus de temps** par
  réponse : sur un agent qui enchaîne huit étapes, ça devient une minute d'attente ;
- aucun des deux ne tient la charge d'un agent qui tourne 24/7 avec des tâches planifiées.

C'est exactement l'argument de la candidature : le goulot n'est pas le modèle, c'est la mémoire
vidéo. 32 Go de VRAM permettent un 32B en Q5, ou un 70B en Q4, ce qui joint la justesse du 8B à une
latence utile, et surtout de traiter en local ce qui ne doit pas sortir du boîtier.

## Méthode et limites

- jeu de 10 tâches courtes et vérifiables → conservateur, il ne mesure pas la qualité
  sur des tâches longues ou ambiguës ;
- latence mesurée côté client, aller-retour complet, machine sans charge concurrente ;
- coût local = 0 € par token, hors électricité et amortissement du GPU ;
- mesure unique : refaire une passe (`--repeat 3`) pour un chiffre défendable en soutenance.

Reproductible avec `bench/bench.py`, voir [`bench/README.md`](../bench/README.md).
