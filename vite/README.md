# Plugin Vite — sync build-info

Copier `sync-build-info.mjs` à la racine du projet (ou `vite/`).

## vite.config.ts

```ts
import { defineConfig } from 'vite'
import { syncBuildInfoPlugin } from './vite/sync-build-info.mjs'

export default defineConfig({
  plugins: [
    syncBuildInfoPlugin({ projectLabel: 'Mon App' }),
  ],
})
```

## Sans Vite

Le dev launcher REFERENCE génère déjà `public/build-info.json` via `syncBuildInfoOnStart`.

## Référence complète

IDLE Isekai : `vite.git-build-info.ts` (Typescript + bump intégré).
