# Politique de versionnement — MTG Tracker

Aligné sur **REFERENCE** : schéma **A.B.C.X.Y**.

Référence globale : [`C:\Dev\Project\REFERENCE\docs\processes\versionnement-global.md`](C:/Dev/Project/REFERENCE/docs/processes/versionnement-global.md)

## Label UI

```
v{A}.{B}.{C}.{X}        (Y = 0)
v{A}.{B}.{C}.{X}.{Y}    (Y > 0)
```

| Exemple | Signification |
|---------|---------------|
| `v1.1.0.05` | Semver 1.1.0, session X=5 |
| `v1.1.0.05.3` | Même X, tâche Y=3 |

**Tag git** `v1.1.0` ≠ **label UI** `v1.1.0.05` — deux vitesses (release vs session agent).

## Segments A.B.C (release)

| Seg. | Événement | Stockage | Commande |
|------|-----------|----------|----------|
| **A** | MEP production | `package.json` major | `npm run version:mep` |
| **B** | Push `main` | minor | git `pre-push` (après `npm run hooks:install`) |
| **C** | Push branche | patch | git `pre-push` |

## Segments X.Y (session agent)

| Seg. | Événement | Stockage | Mécanisme |
|------|-----------|----------|-----------|
| **X** | Nouveau prompt user | `build-revision.json` | Hook Cursor `beforeSubmitPrompt` |
| **Y** | Tâche agent / fin tour | `build-revision.json` | Hook Cursor `stop` |

Opt-out : `même X` / `même Y` / `same X` / `same Y`.

## Fichiers

| Fichier | Versionné | Rôle |
|---------|-----------|------|
| `package.json` | ✅ | Semver A.B.C |
| `version.config.json` | ✅ | Label projet, chemins DEV_LOG |
| `build-revision.json` | ✅ | X, Y, fingerprint |
| `public/build-info.json` | ❌ gitignore | Miroir runtime (`versionLabel`) |
| `docs/traceability/changelog/DEV_LOG_{A}_{B}.md` | ✅ | Journal agent |
| `docs/traceability/changelog/VERSION-INDEX.md` | ✅ | Jalons |
| `docs/traceability/changelog/release-events.jsonl` | ✅ | Événements A/B/C |

## Scripts

```bash
npm run version:prompt      # X+1 (normalement hook)
npm run version:task        # Y+1 (hook stop ou manuel)
npm run version:sync        # sync build-info sans bump
npm run version:branch-push # C+1 (normalement pre-push)
npm run version:main-push   # B+1 (normalement pre-push)
npm run version:mep         # A+1 (manuel, MEP)
npm run hooks:install       # installe .githooks/pre-push
npm run validate:stack      # smoke test infra
```

## Meta version (pas de Y auto)

Changements **uniquement** sur :

- `build-revision.json`
- `docs/traceability/changelog/DEV_LOG_*.md`
- `public/build-info.json`

→ pas de bump Y (évite Y fantôme).

## Vérification hooks

Après redémarrage Cursor (workspace **trusted**) :

1. Envoyer un message test
2. **Hooks Output** → `projectRoot` doit pointer vers `MTG TRACKER`
3. `executionLogLabel` doit afficher `[MTG Tracker]`

## Kickoff nouvelle phase

Voir [`C:\Dev\Project\REFERENCE\docs\processes\kickoff-nouvelle-phase.md`](C:/Dev/Project/REFERENCE/docs/processes/kickoff-nouvelle-phase.md) — reset X/Y, nouveau DEV_LOG, bump semver si besoin.
