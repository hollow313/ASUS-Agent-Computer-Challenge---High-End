# Vérification du jury

Cette page est produite par `make jury-check`, pas écrite à la main. Relancée sur le même commit,
elle sort identique : c'est le point de départ d'une preuve, pas une capture d'écran.

| contrôle | résultat | détail |
| --- | --- | --- |
| tests unitaires | ok | 92 tests |
| scénarios en replay | ok | 9/9 terminés · live uniquement : cyber-brief-live |
| cassettes contre outils réels | ok | toutes les cassettes sont cohérentes avec les outils |
| diagnostic d'installation | ok | prêt |
| dimensionnement 32 Go | ok | qwen2.5-coder-32b 32.8 B Q4 30.4 Go 1.6 Go |

Commit : `cdcddd8`

## Ce que cette page ne dit pas

Elle vérifie la mécanique, pas la qualité d'un modèle. Les chiffres de réussite sont dans
`docs/mesures/`, datés, avec la commande qui les produit. Le détail des scénarios est dans
`docs/SCENARIOS.md`, les runs réels dans `docs/runs/`.

jury-check : OK — 92 tests, 9/9 scénarios, cassettes vertes, fit 32 Go
