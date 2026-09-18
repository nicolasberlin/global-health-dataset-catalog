# Politique de classification, collecte et relance

Date : 2026-09-13.

Statut : contrat cible pour une mise en œuvre progressive. La rédaction de ce
document constitue l'étape 1 ; elle ne modifie pas le comportement de l'application.
Les écarts constatés dans le code sont recensés en section 9.

Mise à jour du 2026-09-18 : après l'étape 2 sur les réponses publiques, trois
corrections ciblées sont réalisées, sans extraction complète des services :

1. La décision et la réservation du job (ou sa réutilisation et l'association)
   sont enregistrées dans une seule transaction. Si la réservation échoue, la
   décision est annulée aussi ; une relance explicite de classification peut
   refaire l'appel IA. Un dataset déjà présent dispense de créer un job.
2. Les jobs existants constituent la file PostgreSQL. Les `pending` survivent au
   redémarrage ; les `running` interrompus passent en erreur. Un consommateur ne
   prend un job que lorsqu'il dispose d'une place. Exploitation avec un seul
   processus et une seule instance API, sans chevauchement lors des déploiements.
3. Rappeler une classification acceptée lit le suivi associé, même après une
   collecte vide ou en erreur. Cela ne réserve ni ne relance une collecte.

La table de demandes, l'admission différée, les nouveaux quotas, les relances de
collecte et les prises en charge renouvelables restent des extensions futures.
La classification persistante et le listing de récupération frontend restent
également séparés. Les sections suivantes décrivent la cible plus large ; cette
mise à jour précise les garanties réellement livrées et le compromis accepté.


Complément du 2026-09-18 — point 4 livré : les demandes de classification sont
persistées dans les candidats existants (`queued`) avant la réponse HTTP 202.
Un worker borné les traite indépendamment des requêtes. Les découvertes `pending`
ne sont jamais exécutées implicitement. Au redémarrage, `queued` reprend et
`classifying` devient `error`, avec relance explicite. La dernière analyse de
l'utilisateur et son suivi sont récupérables par des lectures authentifiées,
sans nouvel appel IA. La migration v3 préserve les données, sans nouvelle table.
Cela remplace les réserves ci-dessus concernant la classification persistante ;
l'historique complet, les leases et les politiques futures restent hors périmètre.

Ce document fixe les comportements à vérifier avant de refactoriser les services.
Il ne définit pas les critères scientifiques d'acceptation des datasets, une
nouvelle politique de licence, ni une garantie d'exécution externe exactement une
fois. Les critères actuels de classification et de validation restent inchangés
pendant l'extraction des services.

## 1. Identité, accès et partage

- Le catalogue reste commun. Les recherches, leurs candidats et leurs décisions
  de classification appartiennent à leur utilisateur.
- Une identité utilisateur provient d'un point d'entrée authentifié du backend.
  Recevoir un `owner_id` en argument ne prouve pas à lui seul cette authentification.
- Un utilisateur consulte un job uniquement si le serveur l'a associé à l'un de
  ses candidats. Connaître son identifiant ou une URL identique ne donne aucun droit.
- Une demande autorisée sur un candidat accepté peut créer cette association lors
  de la création d'un job ou de la réutilisation d'un travail équivalent.
- Cette association autorise la vue publique du job, jamais les recherches, les
  candidats ou l'identité de ses autres participants. Elle ne donne pas accès à
  tout l'historique des jobs de la même URL.
- Les objets absents et les objets inaccessibles renvoient tous deux `404`.
- Les opérations utilisateur passent par des requêtes SQL filtrées. L'interface
  interne des workers reste distincte. Des règles d'import peuvent prévenir les
  contournements accidentels ; les services ne sont pas une frontière d'isolation.

Les associations historiques prouvées sont conservées. Une migration ne déduit
pas de nouveaux droits à partir d'une égalité d'URL.

### Ce qui peut être mutualisé

Une classification dépend du candidat et de son contexte de recherche : elle
n'est pas partagée sur le seul critère d'URL.

Une collecte publique peut être partagée lorsque les entrées qui influencent son
résultat sont équivalentes. Sa clé comprend :

1. l'URL normalisée par la politique commune du backend ;
2. le mode de collecte, notamment page candidate ou découverte d'une source ;
3. une version du traitement couvrant la configuration, les règles et les modèles
   susceptibles de modifier le résultat.

Les paramètres fonctionnels d'une URL sont conservés. On n'assimile pas
automatiquement des miroirs ou des versions de datasets. Des collectes utilisant
à l'avenir des informations ou des accès propres à un utilisateur ne doivent pas
rejoindre ce partage public sans une nouvelle définition de leur périmètre.

Une contrainte SQL assure au plus un job actif par clé de collecte. Cela ne promet
pas qu'un appel externe ne sera jamais répété après une panne.

## 2. Trois notions distinctes

Cette distinction appartient à la cible d'admission différée. L'implémentation
actuelle conserve uniquement les candidats, jobs et associations existants : le
job lui-même porte le travail à effectuer. Aucune table de demandes supplémentaire
n'est nécessaire pour les trois corrections livrées. Si sa réservation échoue,
l'acceptation ne reste pas enregistrée en attente d'une admission ultérieure.

| Notion | Signification |
| --- | --- |
| Classification | Décision de pertinence sur les métadonnées persistées d'un candidat. |
| Demande de collecte | Intention persistée de traiter ce candidat, même si un quota empêche de créer immédiatement un job. |
| Job | Tentative de collecte, éventuellement partagée par plusieurs demandes. |

La première acceptation et l'enregistrement d'une demande de collecte sont
atomiques. Un arrêt ne doit pas laisser une acceptation sans intention récupérable.
Une seule demande initiale existe par candidat et version de classification.

Une demande peut attendre son admission, être différée avec une raison, référencer
un job, ou être satisfaite par un résultat existant. Ces informations ne constituent
pas des copies indépendantes du statut du job.

Un candidat accepté reste accepté lorsque sa collecte est différée, vide ou en
erreur. L'interface affiche séparément la décision et le résultat de collecte.

## 3. Commandes et transitions

### Classification

| État et action | Comportement cible |
| --- | --- |
| `pending` + classifier | Réserver une seule classification sur les données persistées et enregistrer le travail à exécuter. |
| `classifying` + classifier à nouveau | Renvoyer l'état en cours, sans nouvel appel IA. |
| `accepted` ou `rejected` + classifier à nouveau | Renvoyer la décision et le suivi existants, sans créer ni relancer une collecte. |
| `error` + classifier sans relance explicite | Renvoyer un état indiquant qu'une relance explicite est nécessaire. |
| `error` + relance explicite autorisée | Réserver une nouvelle tentative de classification sous les limites applicables. |
| Classification achevée et acceptée | Persister ensemble la décision et la demande initiale de collecte. |
| Classification achevée et rejetée | Persister le rejet ; aucune collecte automatique. |

Une décision acceptée ou rejetée n'est pas recalculée à chaque lecture. Une future
réévaluation après changement des modèles ou des règles est une opération versionnée
distincte, pas un moyen de répéter les votes jusqu'à obtenir une acceptation.

### Admission d'une demande de collecte

L'admission vérifie les droits, l'acceptation du candidat et les entrées serveur.
Elle résout ensuite la demande selon cet ordre :

1. retrouver une commande déjà traitée, si son identifiant est connu ;
2. pour une acquisition ordinaire, réutiliser un dataset déjà disponible ;
3. rejoindre un job actif équivalent en enregistrant l'association ;
4. appliquer la validité d'un résultat vide récent ou un délai lié à la source ;
5. vérifier la capacité d'attente et le quota de nouvelles collectes ;
6. créer le job, l'association et le débit de quota dans une même transaction.

L'absence de quota ne crée pas un job fictif en erreur. La demande reste différée
avec une raison et une date éventuelle de nouvelle admission. Elle peut être reprise
par une action explicite ; consulter son état ne tente pas à nouveau de l'admettre.

Une panne pendant l'admission laisse une demande récupérable. La récupération d'une
intention non encore admise est distincte d'une relance d'un job déjà terminé.

### Lecture, relance et rafraîchissement

- Une lecture ne déclenche aucun travail.
- Une relance explicite après erreur ou résultat vide crée une nouvelle tentative,
  ou rejoint celle déjà créée pour le même travail. Elle respecte la section 5.
- Les anciens jobs terminaux et leurs associations sont conservés. La création
  d'un nouveau job ne fait pas changer silencieusement le job affiché pour tous
  les anciens candidats de la même URL.
- Réutiliser un dataset existant ne signifie pas qu'il vient d'être revérifié :
  l'interface conserve la date de sa dernière vérification.
- Rafraîchir un dataset existant est une opération distincte, hors du premier lot
  de relances. Un futur échec de rafraîchissement ne supprime pas le dernier résultat
  enregistré. La fréquence de rafraîchissement sera définie séparément.
- Changer de recherche, fermer la page ou se déconnecter ne constitue pas une
  annulation des tâches déjà acceptées par le backend. Aucun participant ne peut
  annuler le travail partagé des autres. L'annulation n'est pas ajoutée dans ces lots.

### Répétition d'une commande

Une commande de relance porte un identifiant stable, lié à l'utilisateur, à
l'opération et à la cible. Le serveur conserve son association à la demande ou au
job créé. Répéter la même commande retrouve cette association même si le job est
déjà terminé. Réutiliser le même identifiant avec une autre cible est refusé.

Un refus d'admission n'est pas une tentative de collecte. Une action explicite
ultérieure peut demander une nouvelle admission. L'expiration d'un délai ou un
rafraîchissement de page ne vaut jamais cette action explicite.

## 4. Un résultat vide n'est pas une panne

Les statuts d'exécution restent simples : `pending`, `running`, `done`, `error`.
Le résultat, sa complétude et les causes rencontrées sont enregistrés séparément.

| Situation observée | Résultat à communiquer |
| --- | --- |
| Au moins un dataset admissible a été enregistré | Dataset enregistré ; signaler aussi les vérifications incomplètes éventuelles. |
| Aucun dataset retenu, toutes les vérifications nécessaires dans le périmètre choisi ont abouti | Résultat vide dans le périmètre examiné, avec une raison. |
| Aucun dataset retenu, mais une panne a empêché une vérification nécessaire | Vérification incomplète ; ne pas présenter une absence de dataset comme établie. |
| L'exécution ou sa persistance a échoué | Erreur de traitement, avec une cause structurée. |

`saved_count == 0` ne suffit pas à conclure à un résultat vide fiable. Une limite
d'exploration atteinte doit rester visible : examiner une distribution ne prouve
pas que toutes les distributions de la page sont inutilisables.

Les validations négatives doivent conserver un diagnostic exploitable : erreur
temporaire, limitation distante, accès refusé, ressource absente, contenu incompatible,
destination interdite ou erreur interne. Les exceptions inconnues ne sont pas
reclassées en rejet métier. Un `403` ne prouve pas à lui seul une obligation de
licence ou d'inscription.

Les anciens jobs `done` sans dataset et sans diagnostic restent d'issue inconnue.
Ils ne reçoivent pas rétroactivement une validité de résultat vide de 24 heures.

La sauvegarde des datasets fournis par un résultat et le passage du job à `done`
restent atomiques. Ce contrat n'ajoute pas implicitement la récupération des pages
déjà traitées lorsqu'une autre page fait échouer une collecte multi-page : cette
évolution nécessite son propre changement et ses tests.

## 5. Relances et délais

Les valeurs suivantes sont des réglages initiaux configurables, pas des durées
garanties par les fournisseurs ni des normes de sécurité.

| Cause | Règle initiale | Portée |
| --- | --- | --- |
| Résultat vide fiable | Réutilisable pendant 24 h ; nouvelle tentative explicite ensuite. | Clé de collecte et version du traitement. |
| Panne temporaire d'une ressource | Nouvelle tentative explicite après 5 min depuis la fin de la tentative. | Travail équivalent ; pas seulement le candidat. |
| Limitation distante avec délai connu | Respecter le délai du fournisseur, au minimum le délai local applicable. | Ressource, domaine ou compte fournisseur selon les informations disponibles. |
| Mauvaise configuration, accès refusé ou destination interdite | Ne pas répéter automatiquement la même opération ; une correction ou un changement d'accès doit permettre la reprise. | Dépendance ou ressource concernée. |
| Quota d'un utilisateur dépassé | Nouvelle admission explicite après réouverture du quota. | Cet utilisateur uniquement. |
| Erreur inconnue | Aucun résultat vide réutilisable ; diagnostic interne et pas de répétition automatique aveugle. | Traitement concerné. |

Le délai d'un résultat vide ne se renouvelle pas lors d'une consultation ou de sa
réutilisation. Un nouveau candidat ne contourne pas sa validité. Après expiration,
une nouvelle demande initiale peut lancer le travail ; un ancien candidat accepté
doit passer par l'action explicite de relance.

Une panne commune du fournisseur IA est traitée au niveau de cette dépendance,
sans inscrire chaque URL comme définitivement invalide. Un refus dû au quota
d'Alice n'empêche pas Bob, avec son propre quota, de demander la même source.

Les répétitions internes des lectures HTTP, lorsqu'elles seront ajoutées, sont
limitées à deux répétitions supplémentaires par appel admissible, avec attente
progressive, dispersion des départs et durée totale bornée. Elles respectent les
restrictions du fournisseur et la politique de sécurité réseau à chaque appel.
Le pipeline complet et les appels IA n'acquièrent pas une boucle automatique de
relance par effet de bord. Les budgets des clients et du worker doivent être
examinés ensemble pour éviter leur multiplication.

## 6. Quotas et capacité

| Mesure | Unité et règle |
| --- | --- |
| Limite de requêtes | Demande reçue sur une opération protégée. Plusieurs demandes concurrentes peuvent compter plusieurs unités, même si un seul travail en résulte. |
| Quota de nouvelles collectes | Un job nouvellement admis. Création du job et débit dans la même transaction. |
| Mesure des coûts | Appels IA/HTTP réellement effectués et durée de traitement, suivis séparément des quotas applicatifs. |

Le quota de collecte est attribué à l'utilisateur dont la demande crée le job.
Rejoindre un job, réutiliser un résultat et répéter une commande déjà traitée ne
débitent aucune nouvelle unité de collecte. Ces opérations restent soumises aux
limites de requêtes applicables.

Une tentative créée reste comptabilisée si elle échoue. Une nouvelle tentative
explicite consomme une nouvelle unité. Une reprise interne du même job après perte
d'un worker ne débite pas à nouveau le quota utilisateur ; son coût réel et son
nombre d'exécutions restent mesurés et bornés.

La vérification concurrente du quota et de la capacité utilise la même transaction
que l'admission, avec un ordre de verrouillage constant. Un échec annule la création,
le débit et les associations correspondantes. Aucun appel réseau n'a lieu dans
cette transaction.

Les limites actuelles et leur emplacement sont conservés pendant l'extraction à
comportement constant : recherche 10/minute, classification 20/minute par défaut,
collectes concurrentes 2 par processus. Le quota actuel de classification est
conditionnel aux appels susceptibles de commencer une classification ; ce n'est
pas un compteur exact d'appels IA ni une limite appliquée à tous les appels de lecture.

Avant l'ouverture élargie, le lot quotas doit fixer et tester une limite de nouvelles
collectes, une borne d'attente globale et une borne par utilisateur. Leurs valeurs
dépendent des durées observées et du budget fournisseur ; elles ne sont pas choisies
arbitrairement dans ce document. Les refus de capacité doivent être explicites,
sans file mémoire illimitée ni perte de la demande. Le polling dispose d'une limite
distincte adaptée au suivi ; il ne consomme pas le quota de création.

## 7. Réponses publiques et récupération de l'interface

La conversion publique est implémentée dans
[collector_presenters.py](../backend/app/routes/collector_presenters.py), avec les
modèles de [collector_schemas.py](../backend/app/routes/collector_schemas.py).
Les codes actuels sont génériques : `collection_failed`,
`collection_scheduling_failed`, `classification_failed`, `classifier_vote_failed`
et `validation_failed`. Ils ne prétendent pas encore distinguer les causes de
relance décrites en section 5. Les détails persistés ne sont pas modifiés par la
conversion. Le listing de récupération et les permissions de relance restent à faire.

La lecture d'un job et son inclusion dans une réponse de classification utilisent
la même sélection explicite de champs publics : identifiant du job, URL publique,
état, résultat, compteurs utiles, dates et diagnostic compréhensible.

- Aucun `repository_candidate_id` d'un autre utilisateur n'est exposé dans le job.
- Les erreurs de classification et de collecte passent toutes par des messages
  publics contrôlés ; aucune exception brute ne traverse une autre route.
- La possibilité de relance, sa raison et sa date éventuelle sont évaluées pour
  l'utilisateur courant. Son quota n'est pas enregistré comme statut global du job.
- Les détails techniques sont conservés dans les journaux internes avec un
  identifiant de corrélation. Un contenu externe n'est jamais repris aveuglément
  comme message public.
- Un endpoint paginé permettra de retrouver les demandes et jobs accessibles après
  rechargement ou perte d'une réponse. Il applique les mêmes filtres d'accès.
- Les candidats référencent un job ; le gestionnaire commun fournit son état.
  Une erreur de polling n'est pas une erreur de collecte.

## 8. Exécution durable : cible du dernier lot

Le worker prend les tâches persistées dans PostgreSQL. La classification comme
la collecte cessent de dépendre de la durée de vie d'une requête HTTP.

1. Accuser réception d'un travail accepté seulement après sa persistance.
2. Enregistrer la décision acceptée et son intention de collecte atomiquement.
3. Prendre un job lorsque la capacité d'exécution est disponible ; avant cela il
   reste `pending`.
4. Enregistrer une prise en charge renouvelable avec une génération d'exécution.
5. Récupérer les prises en charge expirées avec un nombre fini de reprises et une
   échéance totale ; au-delà, terminer avec un diagnostic d'interruption.
6. Vérifier la génération courante lors de toute écriture finale, y compris les
   erreurs, afin qu'un ancien worker ne puisse pas écraser une reprise.
7. Conserver la transaction datasets + `done`, sans requête HTTP ni IA sous verrou.

Une perte de worker peut causer la répétition d'un appel externe. Les contraintes
SQL et la génération d'exécution protègent la publication des résultats ; elles
ne rendent pas les services externes exactement une fois. Le budget de reprise,
les échéances et la cadence de renouvellement doivent être fixés et testés dans
ce lot, à partir de la durée maximale des traitements.

Jusqu'à cette migration, conserver l'exploitation avec un seul processus
applicatif et une seule instance. La file de collecte actuelle reprend les jobs
`pending`, mais passe les `running` interrompus en erreur au démarrage. Le passage
à plusieurs instances exige de remplacer cette récupération globale : elle
pourrait invalider le travail d'un autre processus. La classification est désormais consommée depuis les candidats `queued`,
indépendamment de la requête HTTP ; les interruptions en cours exigent une relance.

## 9. Écarts vérifiés et ordre de mise en œuvre

Les liens visent les fichiers ; les fonctions citées permettent de retrouver le
comportement même lorsque les numéros de ligne changent.

| Point constaté dans le code local | Référence | Traitement prévu |
| --- | --- | --- |
| Lecture des jobs déjà filtrée par association et propriétaire. | [collection_jobs.py](../backend/app/db/collection_jobs.py), `get_collection_job_for_owner` | Préserver et tester, sans annoncer la correction comme absente. |
| La primitive interne peut réserver après `error` ou `done` vide ; une première classification d'un nouveau candidat peut donc créer un nouveau job pour la même URL. | [collection_jobs.py](../backend/app/db/collection_jobs.py), `reserve_repository_candidate_collection_job` ; [test_database.py](../tests/test_database.py) | La lecture d'un candidat déjà accepté n'appelle plus cette primitive. L'API de relance reste à définir séparément. |
| Rappeler la classification acceptée lit uniquement le job explicitement associé ou le résultat déjà collecté. | [collector.py](../backend/app/routes/collector.py), `classify_repository_result` ; [collection_jobs.py](../backend/app/db/collection_jobs.py), `get_candidate_collection` | Réalisé et testé pour `pending`, `running`, `done` vide et `error`, y compris avec `retry=true`. |
| Décision acceptée et réservation utilisent la même connexion et transaction. | [classification_completion.py](../backend/app/db/classification_completion.py), `complete_candidate_classification` | Réalisé ; une erreur d'association annule aussi la décision et le nouveau job. Une relance peut refaire l'IA. |
| Des validations HTTP négatives deviennent un compteur, sans préserver leur cause dans le rapport. | [downloads.py](../collector/validation/downloads.py), `probe_url` ; [main.py](../collector/main.py), `_with_valid_distributions_and_report` | Distinguer résultat vide et vérification incomplète avant d'appliquer les délais. |
| La vue publique retire le candidat d'origine et remplace les diagnostics techniques des jobs, candidats, votes et validations. | [collector_presenters.py](../backend/app/routes/collector_presenters.py) ; [collector_schemas.py](../backend/app/routes/collector_schemas.py) | Réalisé à l'étape 2 ; conserver les diagnostics internes et les champs utiles au suivi. |
| Les quotas de requêtes ont leur propre transaction ; aucun quota de création de collecte n'existe. | [api_quotas.py](../backend/app/db/api_quotas.py) ; [security.py](../backend/app/security.py) | Conserver lors de l'extraction ; admission et nouveau quota atomiques dans un lot distinct. |
| Les consommateurs prennent les jobs persistés uniquement quand ils sont disponibles. | [collection_worker.py](../backend/app/collection_worker.py) ; [collection_jobs.py](../backend/app/db/collection_jobs.py), `claim_pending_collection_job` | Réalisé ; attente en PostgreSQL et concurrence bornée. Les prises en charge renouvelables restent futures. |
| Le démarrage préserve les jobs `pending` et marque les `running` interrompus en erreur. | [main.py](../backend/app/main.py), `lifespan` | Réalisé ; aucune reprise automatique d'un job interrompu en cours. Classification en file persistante également, sans reprise des appels interrompus. |
| La sauvegarde des datasets et `done` est déjà atomique. | [collection_completion.py](../backend/app/db/collection_completion.py), `complete_collection_job` | Préserver et tester les échecs de transaction. |
| Le suivi pendant la vie de l'application est séparé ; le listing de récupération backend reste à ajouter. | [Cycle de vie frontend](frontend-job-lifecycle.md) | Compléter la récupération après rechargement. |

| Lot | Livrable et limite du changement | État |
| --- | --- | --- |
| 1 | Ce contrat et les scénarios d'acceptation. Aucun changement d'exécution. | Rédigé |
| 2 | Tests des garanties existantes et correction des réponses publiques. | Réalisé le 2026-09-17 |
| 3 | Extraction des services de collecte, classification et recherche à comportement constant. | À faire |
| 4 | Diagnostics structurés, relances explicites, intentions récupérables et protection contre les commandes répétées. | Partiel : transaction décision–job et classification répétée sans relance réalisées ; reste à faire pour l'admission différée et les commandes de relance. |
| 5 | Quota de nouvelles collectes atomique, délais et limites d'attente. | À faire |
| 6 | Worker durable, récupération des tâches et listing accessible au frontend. | Partiel : file de collecte PostgreSQL et reprise des `pending` réalisées ; classification persistante et restauration de la dernière analyse réalisées ; leases et historique complet à faire. |

Les trois corrections ciblées ci-dessus ont été livrées avant l'extraction des
services ; cette extraction n'était pas nécessaire à leur correction.
Le reste du lot 4 est divisé en corrections vérifiables : d'abord préserver les causes,
puis changer les commandes et leur persistance. Le lot 5 n'utilise un résultat
vide comme résultat réutilisable qu'après cette distinction.

## 10. Scénarios d'acceptation

Cette liste définit des tests à implémenter progressivement. Elle ne constitue pas
une déclaration de tests exécutés ou déjà réussis.

| ID | Scénario | Résultat attendu |
| --- | --- | --- |
| A01 | Alice et Bob demandent simultanément une collecte publique équivalente depuis leurs candidats acceptés. | Un seul job actif en base ; deux associations autorisées. |
| A02 | Charlie connaît l'identifiant du job sans y être associé. | `404` ; aucun accès à son contenu. |
| A03 | Bob lit le job partagé ou le reçoit dans une réponse de classification. | Même vue publique, aucun candidat privé d'Alice ni exception brute. |
| A04 | Deux contextes de recherche concernent la même URL. | Classifications indépendantes ; collecte partagée seulement si ses entrées sont équivalentes. |
| A05 | Un ancien job a une URL identique, sans association historique prouvée. | La migration ne lui accorde pas de nouveaux lecteurs. |
| C01 | Deux demandes de classification concurrentes ciblent le même candidat. | Une seule classification réservée ; limites de requêtes appliquées selon leur contrat. |
| C02 | Une classification acceptée est appelée de nouveau après `done` vide ou `error` de sa collecte. | Aucun nouveau job ni nouvel appel IA. |
| C03 | Une classification est rejetée puis rappelée. | Décision existante ; aucune collecte. |
| C04 | La réservation ou son association échoue pendant la sauvegarde de la décision. | Aucun commit partiel : décision, nouveau job et association sont annulés ensemble. Une relance explicite peut reclassifier. |
| C05 | Le quota empêche la collecte d'un candidat accepté. | Classification conservée, demande différée ; aucun job fictif en erreur. |
| R01 | Deux envois de la même commande de relance, dont le second arrive après la fin du job créé. | Même tentative retrouvée ; aucune seconde création. |
| R02 | Deux utilisateurs relancent simultanément un travail équivalent admissible. | Un seul nouveau job et associations des demandes autorisées. |
| R03 | Un nouveau candidat cible une URL ayant un résultat vide fiable encore valide. | Constat réutilisé sans nouveau travail ni prolongation de sa validité. |
| R04 | La version de traitement change après correction du collecteur. | Ancien constat vide non réutilisé comme résultat de la nouvelle version. |
| R05 | Une distribution expire en timeout sans qu'aucune autre ne valide. | Vérification incomplète ; pas de résultat vide fiable de 24 h. |
| R06 | Aucune ressource n'est retenue et toutes les vérifications nécessaires du périmètre aboutissent. | Résultat vide avec raison et périmètre observé. |
| R07 | Un ancien job est `done`, sans dataset ni diagnostic suffisant. | Issue inconnue ; aucune cause inventée par migration. |
| R08 | Le fournisseur impose une attente, ou l'URL est interdite par la politique réseau. | Respect du délai ou du blocage ; aucune boucle automatique qui le contourne. |
| Q01 | Deux connexions créent simultanément un travail équivalent. | Un seul débit du quota de nouvelles collectes. |
| Q02 | La transaction échoue après le débit mais avant la création complète. | Aucun débit, job ou association partiellement enregistré. |
| Q03 | Alice dépasse son quota ; Bob dispose du sien. | Alice est différée ; Bob peut créer le travail sans blocage global de l'URL. |
| Q04 | Un utilisateur rejoint un job, ou un worker reprend le même job après interruption. | Aucun débit supplémentaire du quota de création. |
| Q05 | La capacité d'attente est épuisée. | Refus d'admission explicite et récupérable ; pas de file mémoire illimitée. |
| E01 | Le processus s'arrête après le commit d'un job de collecte mais avant sa prise en charge. | Le worker retrouve le job `pending` ; les `running` interrompus deviennent des erreurs. |
| E02 | La connexion HTTP disparaît alors que la classification a été acceptée par le backend. | La tâche reste suivie indépendamment de la requête et son résultat est persisté. |
| E03 | Un worker termine après expiration de sa prise en charge et reprise par un autre. | Son résultat et son erreur tardive sont refusés. |
| E04 | Une écriture de dataset échoue pendant la finalisation. | Toutes les écritures de cette transaction sont annulées et le job ne devient pas `done`. |
| E05 | Le budget de reprise d'une tâche est épuisé. | Fin explicite avec diagnostic, sans reprises infinies. |
| F01 | L'utilisateur recharge la page ou perd une réponse de classification. | Ses demandes et jobs sont retrouvés via le backend, sans nouvelles tentatives implicites. |
| F02 | L'utilisateur change de recherche ou se déconnecte pendant une collecte partagée. | Le travail accepté continue ; aucune réponse de l'ancienne session n'alimente la nouvelle. |

Les tests de verrouillage, admission concurrente, quotas et rollback utilisent un
vrai PostgreSQL, plusieurs connexions et une synchronisation provoquant le
chevauchement. Des mocks restent adaptés aux conversions publiques et à
l'orchestration, mais ne démontrent pas ces invariants SQL. Les scénarios
d'interruption testent les frontières de persistance et la génération du worker.

Vérification de l'étape 2 : suite Python avec PostgreSQL 16 temporaire,
343 tests réussis et un test d'intégration du pare-feu ignoré ; 26 tests frontend
réussis et analyse Ruff sans erreur. Le test de concurrence provoque l'attente de
deux connexions PostgreSQL distinctes sur le verrou d'une même URL. Le test HTTP
utilise l'authentification et les associations SQL réelles : utilisateur associé
autorisé, tiers refusé, et même réponse `404` pour un job absent ou inaccessible.
Vérification des trois corrections du 2026-09-18 : 354 tests Python réussis sur
PostgreSQL 16 temporaire, un test de pare-feu ignoré ; 26 tests frontend et build
réussis, Ruff sans erreur. Les 17 tests de [test_collection_workflow.py](../tests/test_collection_workflow.py)
couvrent notamment le rollback réel, l'acceptation concurrente de deux candidats,
les claims concurrents, l'invisibilité avant commit, la reprise au démarrage,
la capacité et l'arrêt des consommateurs, et les classifications répétées.
Les futures politiques de relance, quotas de création et leases restent des
objectifs. La classification persistante et sa récupération sont maintenant
couvertes par les tests de `test_classification_workflow.py` et
`App.classification.test.jsx`.

## Références de conception

- [OWASP — Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) : permissions minimales, contrôles à chaque accès et relations d'autorisation.
- [AWS — Timeouts, retries, and backoff with jitter](https://d1.awsstatic.com/builderslibrary/pdfs/timeouts-retries-and-backoff-with-jitter.pdf) : répétitions bornées et risque de multiplication entre couches.
- [AWS — Transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html) : enregistrer atomiquement un changement et l'intention d'un travail ultérieur.
- [PostgreSQL — Locking clauses](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE) : mécanismes pour la prise de tâches concurrente ; ils ne constituent pas à eux seuls un système de jobs durable.

Ces références justifient les mécanismes. Les politiques de partage, les délais
initiaux et la progression par lots sont des décisions propres à ce projet.


Vérification du point 4 (2026-09-18) : 355 tests Python réussis avec PostgreSQL 16
temporaire, un test d'intégration du pare-feu ignoré ; 33 tests frontend réussis,
build de production et Ruff validés. Les tests couvrent la migration v2 vers v3,
l'exécution sans requête HTTP active, les demandes et claims concurrents, la reprise
après redémarrage, les droits de lecture, la relance explicite et la récupération
de l'interface sans resoumission automatique.
