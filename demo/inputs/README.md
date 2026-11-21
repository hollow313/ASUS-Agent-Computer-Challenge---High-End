# Fichiers de démonstration

Des entrées prêtes à l'emploi, synthétiques, pour tester les scénarios sans rien préparer.

## `audit-demo/`

Quatre fichiers d'audit : `auth.log` (échecs SSH et une connexion réussie), `ss-tlnp.txt` (ports en
écoute), `sshd_config` (directives risquées) et `sudoers.d/webadmin` (règle sudo trop large).

Deux façons de l'utiliser :

1. **rien à faire** : le scénario `local-audit` embarque les mêmes fichiers et les copie dans son
   bac à sable à chaque run. `python3 -m agentdemo run --scenario local-audit` suffit ;
2. **à la main** : copier le contenu dans le dossier d'entrée du run et adapter l'objectif.

## `csv-demo/`

Un CSV de ventes (région, canal, mois, commandes, CA, marge). Dans le conteneur, le pointer depuis
`/settings` avec le chemin absolu du dossier, par exemple `/app/demo/inputs/csv-demo`. Les fichiers
sont alors copiés dans `inputs/` au début de chaque run.

Ces fichiers sont volontairement faux et ne contiennent aucune donnée réelle.
