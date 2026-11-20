# De cette démo à l'agent de production

Cette démo est un extrait propre d'un système qui tourne déjà, en permanence, sur mon matériel.
Le dépôt ne contient volontairement ni l'instance, ni ses données, ni ses identifiants.

## Ce que fait la version de production

| Brique | État |
| --- | --- |
| Service permanent (systemd) sur serveur personnel | en production |
| Pilotage par messagerie (Telegram, WhatsApp) | en production |
| ~90 procédures markdown écrites et corrigées par l'agent lui-même | en production |
| 20 tâches planifiées autonomes (certaines avec reprise par l'agent si le script échoue) | en production |
| Navigateur Chrome piloté en CDP sur une autre machine du réseau local | en production |
| IMAP/SMTP, API de messagerie, MCP (médias, navigateur, périphérique) | en production |
| Routage hybride : modèle cloud pour le raisonnement, modèles locaux (Ollama, LM Studio) pour le reste | en production |
| Vision sur captures d'écran pour vérifier un résultat | en production |

## Trois résultats mesurés sur les 30 derniers jours

1. **Veille cyber quotidienne** : trois sources agrégées, hiérarchisées, briefing daté de 6 à 8
   entrées publié à 8h et envoyé sur messagerie, zéro intervention humaine, avec mode
   « vacances » et rattrapage au retour.
2. **Automatisation de formulaires web** : un moteur piloté par l'agent a ouvert et traité 429
   adresses en six semaines, avec classification automatique des murs (captcha, compte requis,
   clôture) et 51 participations validées. Chaque échec de sélecteur a été réécrit dans une
   procédure réutilisable.
3. **Réservation sportive** : réveil à 00h01 dans la fenêtre d'ouverture, choix des créneaux par
   ordre de préférence, paiement en crédits avec bascule automatique, contrôle et bilan à 6h45.

## Ce que la démo reprend, et ce qu'elle laisse de côté

**Repris** : la boucle objectif → planification → outils → vérification → livrable, le budget
d'étapes, le journal auditable, le bac à sable, l'arrêt propre sur erreur, la séparation
planificateur / outils (donc la possibilité de basculer du cloud vers un modèle local sans
réécrire l'agent).

**Laissé de côté** : la mémoire procédurale persistante, la messagerie comme interface, la
planification cron, le pilotage de navigateur, l'accès réseau réel. Ce sont des briques de
production qui n'ont pas leur place dans une démo que d'autres doivent pouvoir exécuter sans
risque.

## Le point de bascule matériel

L'agent tourne aujourd'hui avec **3 Go de VRAM** : modèles 3-4 B en quantification agressive,
bascule vers le cloud dès que la tâche demande du raisonnement. Trois conséquences mesurables :
coût par token sur les tâches récurrentes, dépendance réseau, et impossibilité de traiter en
local les documents sensibles.

Avec 32 Go de VRAM, la même architecture change de nature : 32 B en Q5, 70 B en Q4 utilisables,
veille et tri de courrier traités hors ligne, index documentaire personnel réaliste, coût
marginal ramené à l'électricité. Le plan de mesure sur 30 jours est dans la candidature.
