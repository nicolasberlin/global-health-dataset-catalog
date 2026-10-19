# Private laboratory observations

This directory holds observations and captures from the optional
[Search Lab](../README.md). The lab has its own commands and interface; it can
read API search diagnostics for analysis. The main API runs independently.

```text
search_lab/data/
├── README.md
├── evidence/
│   ├── <owner-id>/      Snapshots from the Save this candidate action
│   ├── reproductions/  Targeted collector-stage checks
│   └── experiments/    Searches against a separate experimental database
└── captures/           Manually added screenshots
```

## What creates these files?

| Content | Created by | What it records |
| --- | --- | --- |
| `evidence/<owner-id>/*.json` | The lab's **Save this candidate** action | A candidate's observed state, available traces and investigation notes |
| `evidence/reproductions/*.json` | `search_lab.scenarios.run` | An isolated API, HTML, browser or collection check; success at one stage does not prove end-to-end success |
| `evidence/experiments/` | `search_lab.scenarios.experiment search` | Search reports from a separate experimental database |
| `captures/` | A person investigating a result | Screenshots; neither the lab nor `test_api.py` creates these automatically |

Owner IDs group snapshots by identity. JSON filenames identify snapshots that
the lab can reopen and compare; keep those names when moving observations.
The lab defaults to `search_lab/data/evidence/`. `LAB_EVIDENCE_DIR` selects a
different private evidence root, with `reproductions/` and `experiments/` beneath it.

Generated evidence and captures are private and excluded from Git. A fresh clone
contains this guide, not local observations. API client outputs live separately
in [research/api/](../../research/README.md).

## Move or remove observations

Keep snapshot filenames and owner directories when moving evidence. Copy files
without overwriting an existing destination, then update `LAB_EVIDENCE_DIR` if
its location changed. The API client's `--output` and `--cookie-file` options
keep using their explicitly selected paths.

Removing `search_lab/` also removes its local data. Copy `data/` elsewhere first
if you want to retain observations. Experimental PostgreSQL databases and files
under a custom `LAB_EVIDENCE_DIR` have separate lifecycles.
