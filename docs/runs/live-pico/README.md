# Run réel : pico, le chemin le plus court

Date : 25/11/2026. Machine : une carte de 3 Go, modèle `qwen/qwen3-vl-8b` en 4 bits sur LM Studio.
Durée du run : 42.6 s. Statut : done.

    python3 -m agentdemo run --scenario pico --live \
        --model qwen/qwen3-vl-8b --base-url http://127.0.0.1:1234/v1

Étapes :

- [1] fs_read · 16535 ms
- [2] fs_write · 18124 ms
- [3] None · 7912 ms

Le livrable est dans [`pico.md`](pico.md). Ce que ce run démontre : la boucle complète en trois étapes,
sans réseau, sur un petit modèle. Ce qu'il ne démontre pas : la qualité de l'analyse, qui reste celle du
modèle installé à côté.

Ce même scénario est conçu pour tourner avec un modèle de 1,5 milliard sur 8 Go de RAM sans carte
graphique. Le run publié ici a été produit sur un modèle plus gros : le chemin est le même, seules les
latences changent.
