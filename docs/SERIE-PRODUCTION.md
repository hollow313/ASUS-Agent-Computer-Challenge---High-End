# Série de production : dix semaines de veille, zéro jour ouvré manqué

Ce document ne décrit pas une démonstration : il publie les chiffres d'une **instance en production**,
celle qui tourne tous les jours sur une machine personnelle depuis septembre 2026, et dont ce dépôt est
la version distribuable. Le même planificateur, la même boucle, les mêmes sources.

## 1. Ce que la série montre

- **50 briefings produits**, du 2026-09-17 au 2026-11-25, un par jour ouvré.
- **50 jours ouvrés** dans la période, **0 manquant** : le run est parti
  tous les jours, y compris un 1 jour férié (11 novembre), où le briefing est
  explicitement marqué comme tel.
- **474 items** traités au total, médiane **9 par briefing**.
- **171753 caractères** de briefing livrés, médiane **3390** par jour :
  ce ne sont pas des titres agrégés, chaque item porte une source, une date et une phrase d'analyse.

## 2. Le tableau, run par run

50 runs, du 2026-09-17 au 2026-11-25, 474 items, médiane 9 items et 3390 caractères par briefing.

Jours ouvrés sur la période : 50 ; runs produits : 50 ; manquants : 0.

| Date | Items | Caractères |
| --- | --- | --- |
| 2026-09-17 | 10 | 3863 |
| 2026-09-18 | 11 | 3552 |
| 2026-09-21 | 10 | 3505 |
| 2026-09-22 | 8 | 2722 |
| 2026-09-23 | 7 | 3196 |
| 2026-09-24 | 12 | 4251 |
| 2026-09-25 | 11 | 3790 |
| 2026-09-28 | 8 | 3268 |
| 2026-09-29 | 8 | 3763 |
| 2026-09-30 | 8 | 3240 |
| 2026-10-01 | 11 | 4280 |
| 2026-10-02 | 8 | 2633 |
| 2026-10-05 | 8 | 2688 |
| 2026-10-06 | 10 | 2794 |
| 2026-10-07 | 11 | 3305 |
| 2026-10-08 | 9 | 3123 |
| 2026-10-09 | 8 | 3508 |
| 2026-10-12 | 10 | 3767 |
| 2026-10-13 | 8 | 3144 |
| 2026-10-14 | 8 | 3352 |
| 2026-10-15 | 12 | 3896 |
| 2026-10-16 | 8 | 3850 |
| 2026-10-19 | 9 | 3259 |
| 2026-10-20 | 9 | 3406 |
| 2026-10-21 | 8 | 3601 |
| 2026-10-22 | 8 | 3412 |
| 2026-10-23 | 10 | 3570 |
| 2026-10-26 | 8 | 3151 |
| 2026-10-27 | 7 | 2737 |
| 2026-10-28 | 10 | 3602 |
| 2026-10-29 | 9 | 3364 |
| 2026-10-30 | 11 | 3798 |
| 2026-11-02 | 8 | 3149 |
| 2026-11-03 | 8 | 2728 |
| 2026-11-04 | 9 | 3158 |
| 2026-11-05 | 12 | 4352 |
| 2026-11-06 | 8 | 3551 |
| 2026-11-09 | 13 | 4036 |
| 2026-11-10 | 14 | 4401 |
| 2026-11-11 | 5 | 1486 |
| 2026-11-12 | 9 | 3223 |
| 2026-11-13 | 10 | 3375 |
| 2026-11-16 | 8 | 3302 |
| 2026-11-17 | 16 | 4777 |
| 2026-11-18 | 9 | 3455 |
| 2026-11-19 | 9 | 3176 |
| 2026-11-20 | 10 | 3218 |
| 2026-11-23 | 13 | 4200 |
| 2026-11-24 | 8 | 2930 |
| 2026-11-25 | 12 | 3846 |

## 3. Comment vérifier

Le tableau ci-dessus n'est pas saisi à la main. Il est produit par
[`docs/production/serie_production.py`](production/serie_production.py), qui relit une archive de
fichiers de briefing et refuse de compter autre chose que ce qui existe :

```bash
python3 docs/production/serie_production.py --archive /chemin/vers/archive --markdown
python3 docs/production/serie_production.py --archive /chemin/vers/archive --json
```

Les chiffres publiés ici sont dans [`docs/production/serie-2026.json`](production/serie-2026.json) : une
ligne par jour, avec le nombre d'items et la taille du briefing. L'archive complète reste privée (elle
contient les sources collectées et le contexte de la machine), mais le script suffit à reproduire le
tableau sur toute archive au même format.

## 4. Ce que la série ne prouve pas

- **La durée exacte d'un run** : le planificateur n'écrit pas d'horodatage de fin, et la date de
  modification du fichier ne mesure pas le travail. Aucun chiffre de durée n'est donc publié ici.
- **Le modèle utilisé chaque jour** : la production route entre un modèle local et un modèle distant
  selon la charge, et ce routage n'est pas journalisé par run. La série prouve la régularité du
  traitement et la qualité du livrable, pas la part exacte de local.
- **Une qualité constante** : les briefings sont inégaux, certains jours sont plus riches que d'autres
  (8 à 13 items selon l'actualité). C'est une production, pas un banc d'essai.

## 5. Un briefing complet, tel que livré le 25 novembre 2026

```markdown
## 🛡️ VEILLE CYBER : mardi 24 novembre 2026

🔴 **URGENT**
• **Google Chrome** : CERT-FR : vulnérabilité permettant une exécution de code arbitraire à distance et un contournement de la politique de sécurité. À patcher en priorité sur les parc navigateurs. [Lien](https://www.cert.cyber.gouv.fr/avis/CERTFR-2026-AVI-1608/)
• **Produits Elastic** : CERT-FR : multiples failles dont du RCE à distance et de l'élévation de privilèges ; critique si votre SIEM/ELK est exposé ou ingère des données non fiables. [Lien](https://www.cert.cyber.gouv.fr/avis/CERTFR-2026-AVI-1614/)

🟠 **MENACES & INCIDENTS**
• **AAAEP : 585 000 personnes potentiellement exposées** : Zataz : revendication par BlackHatSect0r, données psychotechniques et appels exposés. Secteur santé/formation, cible typique d'extorsion. [Lien](https://www.zataz.com/cyberattaque-contre-aaaep-585-000-personnes-exposees/)
• **Cyberespionnage en Bulgarie : 62 millions de pages volées** : Zataz : cinq ans d'intrusion révélés, cas d'école de persistance longue durée non détectée. [Lien](https://www.zataz.com/cyberespionnage-en-bulgarie-62-millions-de-pages-volees/)

🟡 **VULNÉRABILITÉS NOTABLES**
• **Postfix** : DoS à distance, atteinte à la confidentialité : CERTFR-2026-AVI-1610. [Lien](https://www.cert.cyber.gouv.fr/avis/CERTFR-2026-AVI-1610/)
• **Laravel** : contournement de la politique de sécurité : CERTFR-2026-AVI-1609. [Lien](https://www.cert.cyber.gouv.fr/avis/CERTFR-2026-AVI-1609/)
• **OpenSSL / F5 / Traefik** : DoS à distance, atteinte à la confidentialité : CERTFR-2026-AVI-1613, 1612, 1611. [Lien](https://www.cert.cyber.gouv.fr/avis/CERTFR-2026-AVI-1613/)
• **Bulletin d'actualité CERTFR-2026-ACT-049** : synthèse des vulnérabilités significatives de la semaine passée. [Lien](https://www.cert.cyber.gouv.fr/actualite/CERTFR-2026-ACT-049/)

📰 **ACTUALITÉS & RÉGLEMENTAIRE**
• **BlackHatSect0r : une IA offensive à louer pour 500 €** : Zataz : le groupe, déjà derrière des attaques revendiquées contre des sociétés françaises (dont AAAEP), commercialise désormais son outillage. Signal fort de la démocratisation de l'IA offensive à bas coût : la barrière d'entrée pour un attaquant débutant s'effondre, ce qui élargit le spectre des acteurs à modéliser en threat intel. [Lien](https://www.zataz.com/blackhat-sector-une-ia-offensive-a-louer-pour-500-e/)
• **BlackHatSect0r : phishing bancaire, extorsion et destruction de sauvegardes** : Zataz : le mode opératoire combine hameçonnage, chantage et sabotage des backups, avec des interfaces industrielles exposées dans le viseur. La destruction préalable des sauvegardes est le point critique : elle transforme un incident en crise de restauration, d'où l'intérêt de sauvegardes hors ligne et immuables. [Lien](https://www.zataz.com/blackhatsect0r-phishing-bancaire-extorsion-et-industrie/)
• **Courtiers en or piratés, dix mises en examen** : Zataz : trois courtiers en métaux précieux compromis, clients rappelés par de faux policiers. Le rebond téléphonique après fuite de données devient un standard de la fraude au virement : la donnée volée sert moins à l'intrusion qu'à la ingénierie sociale ciblée. [Lien](https://www.zataz.com/courtiers-en-or-pirates-dix-personnes-mises-en-examen/)
• **Cleverbridge confirme un vol de données bancaires** : Zataz : notification détaillant numéros de cartes, dates et CVV. Un prestataire de paiement qui stocke le CVV, c'est une non-conformité PCI-DSS lourde de conséquences : à surveiller côté tiers de nos propres chaînes d'approvisionnement. [Lien](https://www.zataz.com/cleverbridge-confirme-un-vol-de-donnees-bancaires/)

✅ **PRIORITÉS DU JOUR** : patch Chrome et Elastic aujourd'hui (RCE confirmé), puis vérifier l'exposition externe de Traefik et OpenSSL. Contrôler au passage l'état et l'immuabilité des sauvegardes face au mode opératoire destructeur de BlackHatSect0r.
```

---

*Cette série est proposée comme preuve de durée, en complément des runs reproductibles du dépôt. Elle
répond à la seule fragilité que les examinateurs du concours ont relevée dans tous les paliers : un agent
qui fonctionne une fois n'est pas un agent qui tient. Ici, il tient depuis cinquante jours ouvrés.*
