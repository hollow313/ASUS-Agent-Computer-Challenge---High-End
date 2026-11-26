# À qui sert cette carte, et à quel prix

Cette page ne promet aucun client. Elle décrit trois acheteurs plausibles, ce qu'ils achètent réellement,
et pourquoi une carte de 32 Go change leur réponse. Les prix sont des ordres de grandeur de marché, pas un
tarif pratiqué : rien ici n'a encore été facturé.

## Profil 1 : analyste cyber indépendant

Il produit une veille quotidienne pour deux ou trois clients. Son problème n'est pas la lecture des
sources, c'est la tenue dans le temps : un briefing daté, chaque matin, avec les sources et les échecs.

Ce qu'il achète : le moteur, la veille planifiée, le journal versionné. Chez lui, les sources peuvent être
des flux payants ou des remontées clients, donc rien ne doit sortir.

Prix plausible : **49 € par mois** pour la licence et les mises à jour, le matériel restant à sa charge.
Ce que la carte apporte : un modèle de 32 milliards en local, donc des documents clients analysés sans
transit cloud, et un contexte assez large pour lire un dossier entier plutôt qu'une page.

## Profil 2 : PME ou RSSI externalisé

Il doit produire un audit local rejouable : journaux, ports ouverts, permissions, avec un rapport qu'un
tiers peut contester. Ce qui compte est la reproductibilité, pas la vitesse.

Ce qu'il achète : l'audit et son rapport, pas le logiciel.

Prix plausible : **1 500 € par audit**, une à quatre fois par an. Ce que la carte apporte : l'analyse de
journaux longs sans troncature, et la possibilité de faire relire le rapport par un second modèle avant de
l'envoyer.

## Profil 3 : intégrateur ou agence

Il déploie chez ses propres clients et ne veut dépendre d'aucune API tierce, ni pour le prix, ni pour la
localisation des données.

Ce qu'il achète : une licence de moteur, avec le code lisible et les scénarios comme exemples.

Prix plausible : **2 000 € par an** et par intégrateur, support inclus. Ce que la carte apporte : un
déploiement sur site, sans clé d'API à faire signer par le client.

## Le calcul qui compte : local contre API

Un briefing quotidien de huit entrées coûte environ 12 000 jetons d'entrée et 3 000 de sortie. Aux tarifs
publiés dans [`docs/comparatif-local-cloud.md`](comparatif-local-cloud.md), la même tâche revient à
**0,07 €** avec un modèle d'entrée de gamme et jusqu'à **3 €** avec un modèle de tête. Sur un mois ouvré,
cela fait 1,50 € à 65 € par mois pour un seul usage.

En local, le coût marginal par run est nul : l'électricité d'une carte au repos quelques minutes par jour
n'est pas mesurable. Le coût est donc le matériel, amorti sur douze mois, et le temps d'installation.

Ce que ce calcul dit et ne dit pas : il dit qu'un usage quotidien ne rentabilise pas une carte à lui seul.
Il dit qu'à partir de trois usages (veille, audits, relecture), la carte cesse d'être un achat de confort,
et que ce qui se vend alors n'est pas le prix du jeton, c'est le fait que les données ne sortent pas.

## Ce qui reste à prouver

Rien de ce qui précède n'est validé par un client payant. Les trois profils viennent du travail réel de
l'auteur, pas d'une étude de marché. Un jury doit le lire comme un raisonnement de dimensionnement : la
carte de 32 Go a un acheteur identifiable, avec un geste d'achat et un prix, et le dépôt fournit la preuve
technique que ce prix tient.
