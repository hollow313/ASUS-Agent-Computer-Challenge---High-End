# Sources de la veille

Trois hôtes sont autorisés pour ce run. Il faut les lire, sinon il n'y a pas de veille.

1. CERT-FR, actualités : https://www.cert.ssi.gouv.fr/actualite/
2. Zataz : https://www.zataz.com/
3. 01net, cybersécurité : https://www.01net.com/tag/cybersecurite/

Méthode, dans cet ordre :

1. `http_get` sur chacune des trois URL ci-dessus, une par une.
2. Lire ce qui est publié, garder ce qui compte pour un analyste défense.
3. Écrire `briefing.md` : cinq à huit entrées, chacune avec son lien, son enjeu, et pourquoi c'est
   urgent ou non.
4. Si une source ne répond pas, écrire la ligne « source inaccessible » avec le code, et continuer.

Un briefing sans aucune source lue n'est pas un briefing : c'est un échec, et il doit être annoncé
comme tel.
