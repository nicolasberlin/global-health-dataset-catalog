# Diagnostic d’une recherche

Ce document définit une fiche de traçabilité pour analyser une recherche de bout
en bout, identifier les blocages et rédiger un feedback vérifiable. Il s’applique
à n’importe quelle requête, indépendamment du domaine médical recherché.

Les fichiers fournis sont **des modèles à remplir manuellement**. Ils ne créent
ni endpoint d’export, ni instrumentation, ni journal automatique. Une partie des
informations proposées n’est pas encore conservée par l’application : dans ce
cas, inscrire `null` / `unknown` et décrire la preuve manquante, sans l’inventer.

## Documents à utiliser

1. Copier [trace-recherche.json](templates/trace-recherche.json) dans un dossier
   de diagnostic propre à la recherche. C’est le support structuré des faits.
2. Remplir le contexte, les preuves disponibles, les étapes et les constats.
   Passer `is_template` à `false` ; renseigner la date réelle de l’export.
3. Copier [rapport-recherche.md](templates/rapport-recherche.md) dans ce dossier.
   Rédiger le rapport à partir des identifiants de preuve de la trace.
4. Garder les observations initiales lors d’une correction ou d’une relance.
   Produire une nouvelle trace par tentative et comparer les résultats.

La trace décrit ce qui a été observé. Le rapport explique ce que cela permet de
conclure et les corrections proposées. Aucun de ces documents ne doit présenter
une hypothèse comme une cause établie.

## Informations disponibles dans le projet

| Source | Informations disponibles | Limites |
|---|---|---|
| `GET /collector/searches/{id}/progress` | Statut global, candidats, décisions, diagnostics, jobs, compteurs, IDs enregistrés | Snapshot courant, pas historique de chaque événement |
| `GET /collector/searches/latest` | Dernière recherche accessible au propriétaire | Peut changer après une nouvelle recherche ; garder le `search_id` |
| Logs opérationnels serveur | Événements disponibles, durées et corrélations | Dépendent de la rétention ; ne reconstituent pas tous les liens écartés |
| Lecture autorisée de la base | États persistés, votes et jobs selon les tables | Les raisons détaillées non enregistrées restent inconnues |
| Réseau du navigateur | Requêtes de suivi, statuts, interruptions | Ne montre pas les requêtes sortantes du collecteur serveur |
| Reproduction ciblée | Comportement actuel d’une étape sur une entrée donnée | Ce n’est pas une preuve historique de l’exécution initiale |

Voir [le contrat API](api-integration.md), [le suivi](search-progress.md),
[les résultats du pipeline](pipeline-outcomes.md) et
[les logs opérationnels](DEPLOYMENT.md#internal-operational-logs).
Ne jamais relancer un POST de recherche ou de collecte pour simplement lire
un statut. Une reproduction doit être identifiée comme une nouvelle opération.

## Conventions de la trace

- Dates : ISO 8601 avec fuseau, de préférence UTC ; affichage du rapport en
  `Europe/Zurich`. Durées en millisecondes.
- Valeur inconnue : `null`. Ne pas utiliser `0` pour « non mesuré ».
- Tableaux vides : absence d’entrées renseignées ; leur exhaustivité dépend de
  `export.coverage` et de `export.missing_evidence`.
- `summary.execution_status` et `summary.outcome` gardent les valeurs de l’API.
  Les états ci-dessous servent au diagnostic détaillé, pas à modifier l’API.
- États d’étape : `not_run`, `running`, `succeeded`, `empty`, `rejected`,
  `failed`, `unknown`. Ajouter `reason` et `evidence_refs` lorsque disponibles.
- Ne marquer `not_run` que si une preuve établit que l’étape n’a pas eu lieu.
  Des logs absents ne suffisent pas. `empty` signifie « exécuté sans résultat ».
- `tracking` décrit uniquement les lectures du navigateur. Son arrêt ne prouve
  ni l’arrêt ni l’échec du traitement serveur.
- `frontend_revision` / `backend_revision` désignent les versions réellement
  exécutées. Le dernier commit local ne prouve pas la version déployée.

## Structure des listes à renseigner

Le JSON fourni est un gabarit, pas un JSON Schema ni un nouveau contrat API.
Utiliser les champs suivants pour compléter ses listes. Chaque objet peut
conserver des champs inconnus à `null` et doit référencer ses preuves.

| Liste | Champs recommandés par entrée |
|---|---|
| `context.models` | `voter_id`, `model_id`, `model_version`, `parameters` |
| `context.expected_results` | `reference_url`, `doi`, `expected_decision`, `reason` |
| `sources` | `source_id`, `provider`, `request_query`, `filters`, `limit`, `status`, `http_status`, `result_count`, `excluded_count`, `exclusion_reasons`, `duration_ms`, `errors`, `evidence_refs` |
| `candidates` | `candidate_id`, `source_id`, `title`, `url`, `doi`, `classification_status`, `votes`, `collection`, `files`, `evidence_refs` |
| `candidates[].votes` | `stage`, `voter_id`, `model_id`, `attempt`, `decision`, `relevance`, `reason`, `duration_ms`, `error_code`, `evidence_refs` |
| `candidates[].collection` | `job_id`, `status`, `outcome`, `requested_url`, `final_url`, `http_status`, `content_type`, `discovery_method`, `extracted_link_count`, `excluded_links`, `reason`, `evidence_refs` |
| `candidates[].files` | `file_id`, `url`, `declared_format`, `detected_format`, `download_status`, `http_status`, `bytes_examined`, `validation_status`, `checks`, `reason_code`, `reason`, `dataset_id`, `persistence_status`, `evidence_refs` |
| `events` | `event_id`, `timestamp`, `stage`, `operation`, `search_id`, `candidate_id`, `job_id`, `file_id`, `attempt`, `status`, `duration_ms`, `error_code`, `evidence_refs` |
| `evidence` | `evidence_id`, `kind`, `captured_at`, `artifact_path`, `locator`, `description`, `redacted` |
| `findings` | `finding_id`, `observation`, `proposed_cause`, `confidence`, `evidence_refs`, `missing_verification` |
| `proposed_actions` | `action_id`, `finding_ids`, `priority`, `change`, `expected_result`, `acceptance_test`, `status` |

`confidence` vaut `confirmed`, `hypothesis` ou `undetermined`. La justification
d’un vote est celle retournée par le modèle, pas une reconstruction de son
raisonnement interne. Les limites et délais configurés vont dans
`context.parameters`, avec leur provenance ; ne pas supposer les valeurs par
défaut pour une ancienne exécution.

Exemple de preuve et de constat **fictifs**, à ne pas copier comme résultats :

```json
{
  "evidence": [{
    "evidence_id": "E1",
    "kind": "extractor_reproduction",
    "captured_at": null,
    "artifact_path": "extractor-result.json",
    "locator": "$.usable_link_count",
    "description": "Reproduction ciblée : zéro lien exploitable extrait.",
    "redacted": true
  }],
  "findings": [{
    "finding_id": "F1",
    "observation": "Aucun lien exploitable extrait lors de la reproduction.",
    "proposed_cause": "Liens générés par une interface dynamique.",
    "confidence": "hypothesis",
    "evidence_refs": ["E1"],
    "missing_verification": "Comparer HTML brut, métadonnées API et page rendue."
  }]
}
```

## Questions auxquelles le rapport doit répondre

- La découverte a-t-elle interrogé les bonnes sources avec les bons filtres ?
  Une limite de candidats empêche-t-elle de conclure sur l’ensemble des résultats ?
- Les décisions IA correspondent-elles au besoin ? Une erreur de modèle est-elle
  distinguée d’un rejet valide ? Les tentatives sont-elles identifiées ?
- Pour un candidat accepté, jusqu’à quelle étape la collecte est-elle arrivée ?
  Aucun lien détecté, lien écarté, accès refusé, timeout, format non reconnu,
  fichier invalide et erreur de persistance sont des résultats différents.
- Les résultats ont-ils été enregistrés et rendus accessibles à l’interface ?
- Quelles causes sont établies, lesquelles restent hypothétiques, et quel test
  permettrait de les départager ?

Ne calculer précision ou rappel que si un ensemble de référence annoté existe.
Le nombre de votes positifs ou le taux de fichiers enregistrés ne mesure pas,
à lui seul, la qualité scientifique des résultats.

## Conservation et partage

Conserver les IDs utiles à la corrélation et des extraits minimaux des preuves.
Exclure clés API, cookies, en-têtes d’authentification, URLs signées et contenu
médical brut. Les requêtes peuvent elles-mêmes contenir des informations privées.
Ne pas committer automatiquement les traces réelles : les modèles sont versionnés,
les preuves de chaque exécution doivent être examinées avant partage.
