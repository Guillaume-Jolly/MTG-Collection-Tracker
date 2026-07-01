# Index documentation — MTG Tracker

**Updated:** 2026-06-30  
Lire **avant** d'explorer `docs/` au hasard.

## Source de vérité

| Priorité | Fichier | Contenu |
|----------|---------|---------|
| 1 | [`AGENTS.md`](../AGENTS.md) | Règles inviolables |
| 2 | [`C:\Dev\Project\REFERENCE\docs\INDEX.md`](C:/Dev/Project/REFERENCE/docs/INDEX.md) | Processus multi-projets |
| 3 | [`traceability/project-state.md`](./traceability/project-state.md) | État projet versionné |
| 4 | [`agent-guide/`](./agent-guide/) | Onboarding MTG (PWA, Cardmarket, SQLite) |

## Versionnement

- Schéma **A.B.C.X.Y** : REFERENCE `docs/processes/versionnement-global.md`
- Config locale : `version.config.json`
- Journal actif : `docs/traceability/changelog/DEV_LOG_1_1.md`
- Hooks : `.cursor/hooks.json` + `npm run hooks:install`

## Stack spécifique

| Couche | Emplacement |
|--------|-------------|
| Serveur HTTP | `mtg_pwa/server.py`, `run_mvp.py` |
| DB | `mtg_pwa/database.py`, SQLite sous `data/` |
| PWA | `mtg_pwa/static/` |
| Cardmarket | `mtg_pwa/cardmarket_*.py` |
| Scripts métier | `scripts/*.py` (backfill, prod launcher) |

## Archive

**Jamais supprimer** — move vers gitignore (`old_assets/`, `old_0_1/`, `archive/`).
