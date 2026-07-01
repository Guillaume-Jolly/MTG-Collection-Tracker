/**
 * Fingerprint worktree git — partagé hooks + scripts version.
 */
import { createHash } from 'node:crypto'
import { execSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { readVersionConfig } from './version-config.mjs'

export function runGit(root, command) {
  try {
    return execSync(command, {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    return ''
  }
}

export function getWorktreeFingerprint(root) {
  const head = runGit(root, 'git rev-parse HEAD') || 'unknown'
  const status = runGit(root, 'git status --porcelain')
  const diff = runGit(root, 'git diff HEAD')
  const untracked = runGit(root, 'git ls-files --others --exclude-standard')
  return createHash('sha1')
    .update(head)
    .update('\0')
    .update(status)
    .update('\0')
    .update(diff)
    .update('\0')
    .update(untracked)
    .digest('hex')
    .slice(0, 12)
}

/** Chemins modifiés (porcelain), normalisés slash forward. */
export function getChangedPaths(root) {
  const status = runGit(root, 'git status --porcelain')
  if (!status) return []
  return status
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.slice(3).replace(/\\/g, '/').trim())
    .filter(Boolean)
}

function versionMetaPaths(root) {
  const devLog = readVersionConfig(root).devLogRelativePath.replace(/\\/g, '/')
  return new Set(['build-revision.json', devLog])
}

export function isVersionMetaOnlyChange(root, paths) {
  if (paths.length === 0) return true
  const meta = versionMetaPaths(root)
  return paths.every((p) => meta.has(p.replace(/\\/g, '/')))
}

export function readRevisionState(root) {
  const revisionPath = join(root, 'build-revision.json')
  if (!existsSync(revisionPath)) return null
  try {
    const raw = JSON.parse(readFileSync(revisionPath, 'utf8'))
    if (typeof raw.revision !== 'number') return null
    return raw
  } catch {
    return null
  }
}
