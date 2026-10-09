# Rapport de diagnostic — [requête]

> Modèle à remplir, pas un résultat de test. Remplacer les champs entre crochets.
> Pour la structure de la trace et les règles de preuve, voir
> [le guide](../diagnostic-recherche.md).

## Résultat principal

[En quelques phrases : résultat obtenu, principal blocage établi, conséquence
pour l’utilisateur. Indiquer explicitement les causes encore inconnues.]

## Contexte et objectif

| Champ | Valeur |
|---|---|
| Identifiant de recherche et tentative | [search_id, attempt] |
| Requête exacte | [texte] |
| Date et fuseau | [début, fin, Europe/Zurich] |
| Environnement | [local / test / production] |
| Versions frontend et backend | [commits réellement exécutés, modifications locales] |
| Modèles et paramètres | [versions, limites, délais, filtres] |
| Trace associée | [lien vers trace-recherche.json] |
| Couverture des preuves | [complète / partielle / inconnue ; éléments manquants] |

**Résultat attendu :** [ce que cette recherche doit permettre de trouver et
collecter ; exemples de références connus, si disponibles].

**Critères de réussite :** [pertinence, accès, validation, enregistrement,
durée acceptable]. Préciser si ces critères ont été définis avant l’exécution.

## Bilan observé

| Indicateur | Valeur | Preuve |
|---|---|---|
| Résultats locaux | [nombre ou inconnu] | [evidence_id] |
| Candidats externes | [nombre ou inconnu] | [evidence_id] |
| Candidats acceptés / rejetés / en erreur / encore en cours | [nombres] | [evidence_id] |
| Datasets distincts enregistrés | [nombre, IDs] | [evidence_id] |
| Durée de bout en bout | [durée ou inconnue] | [evidence_id] |
| Statut serveur et résultat global | [valeurs observées] | [evidence_id] |
| État du suivi dans l’interface | [état, dernier succès, éventuel arrêt] | [evidence_id] |

Ne pas confondre candidats acceptés et datasets enregistrés. Dédupliquer les
jobs et datasets partagés. La durée de découverte seule n’est pas celle de la
recherche complète, classification et collecte comprises.

## Analyse par étape

Utiliser les états du guide : non exécuté, en cours, réussi, vide, rejeté,
échoué ou inconnu. « Vide » exige une exécution terminée et une preuve.

| Étape | Résultat observé | État | Preuves | Limites / explication |
|---|---|---|---|---|
| Recherche locale | [résultat] | [état] | [IDs] | [texte] |
| Découverte externe | [sources, requêtes, limites, filtres, résultats] | [état] | [IDs] | [texte] |
| Classification IA | [votes par modèle, décision, erreurs et tentatives] | [état] | [IDs] | [texte] |
| Collecte et extraction | [URL initiale/finale, HTTP, méthode, liens trouvés] | [état] | [IDs] | [texte] |
| Validation des fichiers | [tentatives, formats, contrôles, échecs] | [état] | [IDs] | [texte] |
| Enregistrement | [IDs, résultat de persistance] | [état] | [IDs] | [texte] |

## Détail des candidats significatifs

Répéter cette fiche pour chaque blocage, faux positif ou réussite utile à comparer.

- **Candidat / job :** [identifiants, titre, URL publique, DOI].
- **Attendu :** [pourquoi ce candidat devrait être accepté/rejeté ou collecté].
- **Votes IA :** [par modèle : décision, justification retournée, tentative,
  diagnostic ; distinguer les votes de pertinence des votes sur la page].
- **Accès à la page :** [URL initiale/finale, HTTP, MIME, durée, preuves].
- **Extraction :** [méthode, liens trouvés, liens écartés et motifs].
- **Fichiers :** [pour chacun : URL publique, format annoncé/détecté,
  téléchargement tenté ou non, contrôle effectué, résultat, motif précis].
- **Persistance :** [dataset enregistré, ID ou motif de non-enregistrement].
- **Conclusion :** [cause confirmée / hypothèse / indéterminée ; preuves].

## Constats et causes

| ID | Observation | Cause proposée | Niveau de preuve | Références | Vérification manquante |
|---|---|---|---|---|---|
| F1 | [fait observable] | [cause ou inconnue] | [confirmé / hypothèse / indéterminé] | [IDs] | [test ciblé] |

Une reproduction actuelle ne prouve pas à elle seule la cause d’une ancienne
exécution. Dater les preuves et indiquer la version concernée.

## Corrections proposées

| Priorité | Action | Constat lié | Résultat attendu | Test d’acceptation |
|---|---|---|---|---|
| [haute/moyenne/basse] | [changement concret] | [F1] | [comportement] | [test reproductible] |

Séparer les corrections du collecteur, l’amélioration des diagnostics et les
changements de message dans l’interface. Corriger un libellé ne corrige pas la
collecte. Les actions proposées ne sont pas considérées comme réalisées.

## Vérification après correction

[À compléter après mise en œuvre, ou indiquer « non réalisée ».]

| Version / recherche | Scénario | Avant | Après | Verdict et preuves |
|---|---|---|---|---|
| [commit, search_id] | [même entrée / fixture contrôlée] | [résultat] | [résultat] | [IDs] |

Préciser les appels réseau ou modèles effectués et les différences de paramètres.
Une relance manuelle constitue une nouvelle tentative ; conserver les preuves
initiales pour comparer.

## Annexes et limites

- [Liens vers snapshots API, extraits de logs expurgés et fixtures pertinentes].
- [Informations indisponibles et conclusions qu’elles empêchent].
- [Éventuelles expurgations ; aucun jeton, cookie, clé ou contenu médical brut].
