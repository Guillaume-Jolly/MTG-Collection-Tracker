# Dev Launcher — template REFERENCE

Lanceur dev local générique (inspiré IDLE Isekai + MTG Tracker) :

- démarre `npm run dev` (script configurable)
- dashboard monitoring sur port configurable
- affichage versions (`build-info.json`, `build-revision.json`, git)
- logs, restart, build optionnel

## Install sur un projet

```powershell
cd C:\Dev\Project\REFERENCE
node scripts/install-dev-launcher.mjs "C:\Dev\Project\MonApp"
```

Ou inclus dans `bootstrap-project.mjs` (copie automatique).

## Config — `dev-launcher.config.json` (racine projet)

Copier depuis `dev-launcher.config.example.json` :

| Clé | Défaut | Rôle |
|-----|--------|------|
| `projectLabel` | nom dossier | Titre dashboard |
| `dashboardPort` | 9221 | Port tableau de bord |
| `devPort` | 5173 | Port app (fallback si Vite ne log pas l'URL) |
| `devHost` | 127.0.0.1 | Host app |
| `devScript` | `dev` | Script npm à lancer |
| `buildScript` | `build` | Script build optionnel |
| `buildInfoRelativePath` | `public/build-info.json` | Fichier version runtime |
| `syncBuildInfoOnStart` | true | Génère build-info sans plugin Vite |
| `accentColor` | `#7eb8ff` | Couleur UI dashboard |

Variables d'environnement : `DEV_LAUNCHER_DASHBOARD_PORT`, `DEV_LAUNCHER_DEV_PORT`.

## Usage

```powershell
npm run dev:launcher
# ou double-clic Dev Launcher.bat
```

## Projets Vite (IDLE)

Garder le plugin `vite.git-build-info` existant — le lanceur **observe** `public/build-info.json`.

## Projets sans Vite (site statique, Python, etc.)

- Ajuster `devScript` / `devPort`
- Laisser `syncBuildInfoOnStart: true` pour label version basique

## Gitignore

Ajouter : `scripts/dev-launcher/.dev-session/`
