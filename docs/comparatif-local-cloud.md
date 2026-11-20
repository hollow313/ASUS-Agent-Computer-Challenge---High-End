# Comparatif local contre cloud

Mesures réelles du 20/11/2026, mêmes 10 tâches vérifiables, même prompt système, température 0,
notation par correspondance exacte. Les modèles locaux tournent sur mon GPU actuel (3 Go de VRAM)
via LM Studio en Q4 ; le modèle cloud est appelé sur son API publique.

| Cible | Modèle | Réussite | p50 | p95 | Coût / 1 000 tâches |
| --- | --- | --- | --- | --- | --- |
| Local 7B | qwen2.5-coder-7b, Q4 | 60 % | 0,48 s | 0,93 s | 0 € |
| Local 8B vision | qwen3-vl-8b, Q4 | 90 % | 18,9 s | 38,2 s | 0 € |
| Cloud | deepseek-flash | 100 % | 1.02 s | 1.61 s | 0.05 € |

## Ce que ces chiffres disent vraiment

Trois constats, dont deux qui ne vont pas dans le sens du discours habituel.

1. **Le cloud gagne sur la justesse et la latence.** 100 % des tâches, une seconde de médiane.
   Aucun modèle de 7-8B sur 3 Go de VRAM n'approche ça : soit il est rapide et faux, soit il est
   juste et trente-neuf fois plus lent.
2. **Le coût n'est pas l'argument à mon volume.** À 5 centimes les 1 000 exécutions, une
   installation qui ferait 4 000 appels par mois dépenserait 0,20 €. Dire « la carte s'amortit sur
   le coût des tokens » serait malhonnête à cette échelle, et un reviewer fera le calcul.
3. **DeepSeek est l'hypothèse la plus favorable au cloud.** C'est aujourd'hui l'un des tarifs les
   plus bas du marché. Sur les modèles de gamme supérieure (OpenAI, Anthropic, Gemini), la même
   charge coûte de l'ordre de dix à quarante fois plus : le chiffre ci-dessus est donc un plancher,
   pas une moyenne.

## Alors pourquoi 32 Go ?

Pour trois raisons qui tiennent devant un jury technique.

**La souveraineté.** Une partie de ce que traite l'agent ne peut pas partir sur une API : données
clients, courrier personnel, archives. Aujourd'hui ces tâches basculent sur le cloud parce que le
matériel local n'a pas la mémoire nécessaire. Avec 32 Go, elles restent sur la machine, et ce
n'est pas négociable quand on est analyste.

**La parité de qualité en local.** Un modèle 32B en Q5 tient entièrement dans 32 Go. C'est le
palier où le local cesse d'être un compromis : on garde 90 % et plus sur des tâches vérifiables,
avec un contexte long, sans arbitrer entre vitesse et justesse. Les 8B testés ici montrent
justement la marche à franchir.

**La disponibilité.** Un agent qui tourne 24 heures sur 24 avec des tâches planifiées ne peut pas
dépendre d'un quota, d'une panne d'API ou d'un changement de tarif. Local veut dire prévisible.

## Ce qui resterait sur le cloud

Le raisonnement complexe et les tâches où la qualité prime sur la confidentialité continueront de
passer par une API, au cas par cas. L'agent route déjà entre local et cloud : la carte ne remplace
pas le cloud, elle déplace la frontière de ce qui doit rester dedans.

## Méthode et limites

- 10 tâches courtes et vérifiables : extraction, classement, calcul, date. Jeu conservateur, il ne
  mesure pas la qualité sur des tâches longues ou ambiguës.
- une seule passe par cible ; refaire avec `--repeat 3` pour un chiffre défendable en soutenance.
- latence mesurée côté client, aller-retour complet, machine sans charge concurrente.
- coût cloud calculé sur les tokens réellement rapportés par l'API et le tarif public hors pointe
  (0,15 $ entrée et 0,60 $ sortie par million, convertis à 0,92). La pointe double ces tarifs.
- coût local à 0 € par token, hors électricité et amortissement du matériel.

Reproductible : `python3 bench/bench.py --targets bench/targets.json` (voir
[`bench/README.md`](../bench/README.md)).
