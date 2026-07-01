# Manifeste cleanup — fin de phase 0.1

**Date :** 2026-06-30  
**Phase quittée :** `0.1` (semver `0.1.16`)  
**Archive :** `old_0_1/`

## Contenu archivé (move only)

| Chemin | Raison |
|--------|--------|
| `old_0_1/cursor-hooks-legacy/` | Anciens hooks `bump-version-on-*.mjs` (pré-REFERENCE) |
| `old_0_1/scripts-legacy/version-core.mjs` | Ancien sync semver X/Y seul |
| `old_0_1/pre-reference-upgrade/` | Backup scripts Python avant upgrade REFERENCE |
| `old_0_1/launcher-tkinter/` | Panneau dev tkinter (remplacé par `npm run dev:launcher`) |

## Non archivé (conservé actif)

- `launcher/dev_control_panel.py` — accessible via `launch_dev_tkinter.bat`
- Scripts métier `scripts/*.py`, `scripts/prod_launcher/`

## Hygiène post-clôture

- DEV_LOG 0.1 finalisé → `DEV_LOG_0_1.md`
- MEP A → `1.0.0`
- Kickoff phase `1.1` → `DEV_LOG_1_1.md`, reset `build-revision.json`
