# Trace réelle : capture lue par un modèle vision local

Date : 24/11/2026, 17 h 12 UTC. Machine : carte de 3 Go. Modèle : `qwen/qwen3-vl-8b` en 4 bits,
servi par LM Studio sur `192.168.1.153:1234`.

Commande :

    python3 -m agentdemo run --scenario capture-audit --live \
        --model qwen/qwen3-vl-8b --base-url http://192.168.1.153:1234/v1

Résultat : statut `done`, 3 étapes, un livrable `RAPPORT-CAPTURE.md`.

Étapes du journal :

[1] image_probe 18358 ms
[2] fs_write 49655 ms
[3] None 12131 ms

Le rapport produit est dans [`RAPPORT-CAPTURE.md`](RAPPORT-CAPTURE.md). Quatre constats, chacun avec une
zone en pixels. Deux zones sont justes au pixel près (le bandeau, en haut, et le pied de tableau), deux
sont approximatives : le modèle a lu l'image, mais il ne localise pas une zone comme un outil de mesure.
C'est exactement la raison pour laquelle `image_probe` existe et pourquoi la revue par un second modèle
existe aussi.

L'image d'entrée n'apparaît pas dans les livrables : elle entre dans le bac à sable, elle n'en sort pas.
