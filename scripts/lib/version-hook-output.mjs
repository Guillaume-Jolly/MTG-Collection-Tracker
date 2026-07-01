/**
 * Libellés hooks + label lisible pour le journal Cursor (Output JSON).
 */
import { readFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { readRevisionState } from './worktree-fingerprint.mjs'

export const VERSION_HOOK_X_NAME = 'A.B.C.X.Y - X update - prompt indent'
export const VERSION_HOOK_Y_NAME = 'A.B.C.X.Y - Y update - subprompt indent'

function readPackageName(root) {
  try {
    const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
    return typeof pkg.name === 'string' ? pkg.name : basename(root)
  } catch {
    return basename(root)
  }
}

export function formatVersionLabel(root, stateOverride) {
  const state = stateOverride ?? readRevisionState(root)
  let semver = '0.0.0'
  try {
    semver = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version
  } catch {
    /* ignore */
  }
  const x = state?.revision ?? 0
  const y = state?.subRevision ?? 0
  return y > 0 ? `v${semver}.${x}.${y}` : `v${semver}.${x}`
}

/**
 * Label court : projet + version + action — affiché en tête du JSON Output.
 * (La colonne « windows_temp_file » dans la liste Cursor n'est pas modifiable côté script.)
 */
export function buildExecutionLogLabel(root, versionHook) {
  const record = versionHook?.record ?? {}
  const folder = record.projectFolder ?? basename(root)
  let releaseSemver = '0.0.0'
  try {
    releaseSemver = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version
  } catch {
    /* ignore */
  }
  const version =
    record.versionLabel ??
    (record.revision != null
      ? formatVersionLabel(root, { revision: record.revision, subRevision: record.subRevision ?? 0 })
      : formatVersionLabel(root))

  let action = record.action ?? 'run'
  if (record.action === 'skip') action = `skip (${record.reason ?? '—'})`
  if (record.action === 'bump-x') action = 'bump X'
  if (record.action === 'bump-y') action = 'bump Y'

  return `${folder} · ${version} · release A.B.C=${releaseSemver} · ${action}`
}

export function enrichHookPayload(root, hookName, versionHook, extra = {}) {
  return {
    ...extra,
    hookName,
    executionLogLabel: buildExecutionLogLabel(root, versionHook),
    projectName: readPackageName(root),
    projectFolder: basename(root),
    versionHook,
  }
}
