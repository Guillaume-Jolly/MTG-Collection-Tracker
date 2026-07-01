/**
 * Lit version.config.json à la racine du projet cible.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const DEFAULTS = {
  projectLabel: 'project',
  devLogRelativePath: 'docs/traceability/changelog/DEV_LOG.md',
  versionIndexRelativePath: 'docs/traceability/changelog/VERSION-INDEX.md',
  releaseEventsRelativePath: 'docs/traceability/changelog/release-events.jsonl',
  gitignoreArchiveDirs: ['old_assets/', 'old_v2.1/', 'old_2_2/', 'archive/'],
}

export function readVersionConfig(root) {
  const path = join(root, 'version.config.json')
  if (!existsSync(path)) return { ...DEFAULTS }
  try {
    return { ...DEFAULTS, ...JSON.parse(readFileSync(path, 'utf8')) }
  } catch {
    return { ...DEFAULTS }
  }
}

export function devLogPath(root) {
  return join(root, readVersionConfig(root).devLogRelativePath)
}

export function releaseEventsPath(root) {
  return join(root, readVersionConfig(root).releaseEventsRelativePath)
}

export function projectLabel(root) {
  return readVersionConfig(root).projectLabel
}
