#!/usr/bin/env node
/**
 * Resync public/build-info.json git metadata without bumping X or Y.
 */
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readDevLauncherConfig } from './dev-launcher/lib/config.mjs'
import { syncBuildInfo } from './dev-launcher/lib/sync-build-info.mjs'
import { projectLabel } from './lib/version-config.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const config = readDevLauncherConfig(root)
const payload = syncBuildInfo(root, config)
const label = payload?.versionLabel ?? '?'
console.log(`[${projectLabel(root)}] Sync build-info → ${label}`)
