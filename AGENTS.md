# AGENTS.md — MTG Tracker

Guide pour agents Cursor travaillant sur ce dépôt.

## Source de vérité process

| Priorité | Fichier |
|----------|---------|
| 1 | Ce fichier |
| 2 | [`C:\Dev\Project\REFERENCE\docs\INDEX.md`](C:/Dev/Project/REFERENCE/docs/INDEX.md) |
| 3 | [`docs/DOC_AGENT_INDEX.md`](docs/DOC_AGENT_INDEX.md) |
| 4 | [`docs/traceability/project-state.md`](docs/traceability/project-state.md) |

## Versionnement A.B.C.X.Y

**Référence globale :** [`C:\Dev\Project\REFERENCE\docs\processes\versionnement-global.md`](C:/Dev/Project/REFERENCE/docs/processes/versionnement-global.md)  
**Détail projet :** [`docs/agent-guide/05-politique-versionnement.md`](docs/agent-guide/05-politique-versionnement.md)

| Seg. | Événement | Mécanisme |
|------|-----------|-----------|
| **A** | MEP prod | `npm run version:mep` (manuel) |
| **B** | Push `main` | git `pre-push` auto |
| **C** | Push branche | git `pre-push` auto |
| **X** | Nouveau message user | Hook `beforeSubmitPrompt` (opt-out `même X`) |
| **Y** | Fin de tour agent (fichiers modifiés) | Hook `stop` (opt-out `même Y`) |

## Phase active

- **Semver :** `1.1.0` (phase 1.1 post-MEP)
- **MEP livrée :** `1.0.0` (2026-06-30)
- Journal : `docs/traceability/changelog/DEV_LOG_1_1.md`

### DEV_LOG

- Chaque bump **X** ouvre une section `### X=N — ⚠️ À COMPLÉTER`
- **1 ligne Y ≈ 1 commit atomique**
- En fin de prompt satisfait : finaliser la section → **Historique complété**

### Meta version (pas de Y auto)

Changements **uniquement** sur `build-revision.json`, DEV_LOG, `public/build-info.json` → hook `stop` ignore.

## Stack

- **Backend** : Python 3.11+, SQLite, `python run_mvp.py` (port **8000**)
- **Frontend** : PWA vanilla (`mtg_pwa/static/`)
- **Version UI** : `v{A}.{B}.{C}.{XX}` ou `….{Y}` via `mtg_pwa/version.py` + `public/build-info.json`

## Dev

```bash
npm run dev:launcher    # dashboard web (port 9222) + serveur Python
npm run dev:server      # serveur seul
launch_dev_tkinter.bat  # ancien panneau tkinter (archivé dans old_0_1/launcher-tkinter/)
```

Brave par défaut : `dev-launcher.config.json` → `browserExecutable`.

## Tests & validation

```bash
npm run validate:stack
python -m unittest discover -s tests -v
```

## Hooks

- Cursor : `.cursor/hooks.json` — redémarrer Cursor après modif
- Git : `npm run hooks:install` → `.githooks/pre-push`
- Debug : [`.cursor/hooks/README.md`](.cursor/hooks/README.md) — vérifier `projectRoot` = ce dépôt dans Hooks Output

## Règles Cursor

- `01-no-deletion-archive-only` — jamais supprimer, move vers `old_0_1/` / `archive/`
- `02-version-prompt-first` — X/Y, DEV_LOG
- `03-version-release-ABC` — A/B/C sur push
- `04-secrets-env` — pas de secrets commités

## Archive

Reliquats infra : `old_0_1/` (gitignore). Ne pas `git rm` sans instruction explicite.
