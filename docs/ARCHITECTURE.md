# Vigie, architecture

## Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────────┐
│ interface web (1 page, /api/*) CLI (python -m agentdemo) │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                        ┌───────▼────────┐
                        │ Agent.run() │ boucle bornée par max_steps
                        └───────┬────────┘
                ┌───────────────┴────────────────┐
                │ │
      ┌─────────▼─────────┐ ┌─────────▼──────────┐
      │ Planner │ │ Tool registry │
      │ replay | live │ │ 8 outils │
      └─────────┬─────────┘ └─────────┬──────────┘
                │ │
   cassette.json │ décisions ┌──────────▼──────────┐
   modèle local │ (OpenAI-compat.) │ Sandbox (1 run) │
                                     │ écrit / déplace │
                                     └──────────┬──────────┘
                                                │
                                    data/runs/<id>/workspace + journal JSON
```

## Le cycle

1. `Agent.run(objective)` prépare un `Sandbox` et un registre d'outils liés à ce run.
2. À chaque tour, le `Planner` renvoie **une** action : soit un appel d'outil, soit une
   conclusion (`final`).
3. L'action est exécutée. Toute erreur (`ToolError`, arguments invalides, outil inconnu) devient
   une **observation** que l'agent voit au tour suivant, il peut se corriger, comme en
   production quand un sélecteur CSS casse.
4. Chaque étape est publiée à l'interface via un callback (`on_step`) et journalisée.
5. La boucle s'arrête sur `final` (statut `done`), sur échec de planification (`failed`), ou sur
   budget épuisé (`budget`).

## Choix techniques

**Bibliothèque standard uniquement.** `http.server`, `urllib`, `csv`, `json`, `xml.etree`.
Aucune couche à installer, donc aucun prérequis pour tester la démo : c'est une contrainte
produit, pas une contrainte technique. Un jury ne doit pas avoir à résoudre un conflit de
versions.

**Replay + live derrière la même interface.** Le protocole est un objet JSON unique :
`{"thought": "...", "tool": "...", "args": {...}}` ou `{"thought": "...", "final": "..."}`.
N'importe quel modèle qui sait produire du JSON peut piloter l'agent, et l'extraction tolère
les clôtures Markdown que les modèles ajoutent souvent.

**Bac à sable par résolution de chemin.** `Sandbox.resolve()` refuse tout chemin qui sort du
répertoire du run, y compris par symlink. Les outils n'ont pas d'accès direct au système de
fichiers : ils reçoivent une `Sandbox`, pas un `Path`.

**Journal avant interface.** Le fichier `data/runs/<run_id>.json` est écrit par l'agent lui-même,
indépendamment de l'interface. Un run reste donc auditable même si personne n'a regardé l'écran,
et l'interface ne fait que lire cet état.

**Pas de mémoire cachée.** Une exécution est reproductible : même objectif, même cassette, même
résultat, octet pour octet (les livrables sont déterministes, seuls les temps d'exécution
varient).

## Limites assumées

- Mono-utilisateur, pas d'authentification sur l'interface : c'est une démo locale.
- État des runs en mémoire (les journaux, eux, sont sur disque).
- Aucune parallélisation des appels d'outils : un agent qui agit sur un disque doit d'abord
  rester lisible et débogable.

## Robustesse

Quatre mécanismes, chacun avec son test.

- **Repli** : `Target.fallback` déclare des cibles de secours, `FallbackPlanner` bascule une seule fois
  par étape sur une erreur de transport, et journalise `from`, `to`, `reason`.
- **Reprise** : `runs/<id>/state.json` est écrit en atomique après chaque étape ; `Agent.run(resume=...)`
  restaure historique, compteurs, artefacts et numérotation. Un état tronqué donne un message clair,
  jamais une trace.
- **Revue** : `agentdemo/review.py` fournit `ReplayReviewer` (verdicts enregistrés) et `ModelReviewer`
  (second modèle). Un verdict inconnu vaut rejet, deux relectures au maximum.
- **Autorisations** : le serveur tient une file de demandes par run, l'agent attend la décision avec une
  expiration à 120 secondes, et les valeurs sensibles sont masquées dans les pensées, les observations
  et le bilan.
