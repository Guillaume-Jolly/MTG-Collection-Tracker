/**
 * Log hooks version — identifie clairement QUEL repo/projet a exécuté le bump.
 * Retourne un objet pour l'inclure dans le JSON stdout du hook (visible dans l'UI Cursor).
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { readRevisionState, runGit } from './worktree-fingerprint.mjs'

const LOG_PREFIX = '[version-hook]'

function readPackageName(root) {
  try {
    const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
    return typeof pkg.name === 'string' ? pkg.name : basename(root)
  } catch {
    return basename(root)
  }
}

function readLastRunPath(root) {
  return join(root, '.cursor', 'hooks', 'last-run.json')
}

function readLastRun(root) {
  const path = readLastRunPath(root)
  if (!existsSync(path)) return {}
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return {}
  }
}

function writeLastRun(root, patch) {
  const path = readLastRunPath(root)
  mkdirSync(join(root, '.cursor', 'hooks'), { recursive: true })
  const next = { ...readLastRun(root), ...patch, updatedAt: new Date().toISOString() }
  writeFileSync(path, `${JSON.stringify(next, null, 2)}\n`)
}

/** Identité projet sans appels git lourds — log immédiat en début de hook. */
export function peekVersionHookProject(root) {
  const state = readRevisionState(root)
  return {
    projectName: readPackageName(root),
    projectFolder: basename(root),
    projectRoot: root,
    revision: state?.revision ?? null,
    subRevision: state?.subRevision ?? null,
  }
}

/**
 * @param {string} root
 * @param {{
 *   hook: 'beforeSubmitPrompt' | 'stop'
 *   hookName?: string
 *   action: 'bump-x' | 'bump-y' | 'skip'
 *   reason?: string
 *   versionLabel?: string
 *   error?: string | null
 * }} entry
 * @returns {{ summary: string, record: Record<string, unknown> }}
 */
export function logVersionHook(root, entry) {
  const state = readRevisionState(root)
  const record = {
    at: new Date().toISOString(),
    hook: entry.hook,
    hookName: entry.hookName ?? null,
    action: entry.action,
    reason: entry.reason ?? null,
    versionLabel: entry.versionLabel ?? null,
    error: entry.error ?? null,
    projectName: readPackageName(root),
    projectFolder: basename(root),
    projectRoot: root,
    gitBranch: runGit(root, 'git rev-parse --abbrev-ref HEAD') || 'unknown',
    gitHead: runGit(root, 'git rev-parse --short HEAD') || 'unknown',
    revision: state?.revision ?? null,
    subRevision: state?.subRevision ?? null,
  }

  const label = entry.hookName ?? entry.hook
  const summary =
    entry.action === 'skip'
      ? `${LOG_PREFIX} SKIP ${label} | ${record.projectName} | ${record.projectRoot} | ${entry.reason ?? '—'}`
      : `${LOG_PREFIX} ${entry.action.toUpperCase()} ${label} | ${record.projectName} | ${record.projectRoot} | ${entry.versionLabel ?? `X=${record.revision} Y=${record.subRevision}`}`

  const key = entry.hook === 'beforeSubmitPrompt' ? 'lastPrompt' : 'lastTask'
  writeLastRun(root, { [key]: record })

  return { summary, record }
}
