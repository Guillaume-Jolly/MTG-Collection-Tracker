/**
 * Génère public/build-info.json depuis package.json + build-revision.json + git.
 * Projets sans plugin Vite dédié peuvent l'appeler au démarrage du lanceur.
 */
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

function runGit(root, command) {
  try {
    return execSync(command, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return ''
  }
}

function formatVersionLabel(semver, revision, subRevision) {
  const build = String(Math.max(0, revision)).padStart(2, '0')
  if (subRevision > 0) return `v${semver}.${build}.${subRevision}`
  return `v${semver}.${build}`
}

export function syncBuildInfo(root, config) {
  const pkgPath = join(root, 'package.json')
  if (!existsSync(pkgPath)) return null

  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'))
  const semver = typeof pkg.version === 'string' ? pkg.version : '0.0.0'

  let revision = 1
  let subRevision = 0
  const revisionPath = join(root, config.revisionRelativePath)
  if (existsSync(revisionPath)) {
    try {
      const raw = JSON.parse(readFileSync(revisionPath, 'utf8'))
      if (typeof raw.revision === 'number') revision = raw.revision
      if (typeof raw.subRevision === 'number') subRevision = raw.subRevision
    } catch {
      /* ignore */
    }
  }

  const commitHash = runGit(root, 'git rev-parse --short HEAD') || 'unknown'
  const branch = runGit(root, 'git rev-parse --abbrev-ref HEAD') || 'unknown'
  const dirty = runGit(root, 'git status --porcelain') !== ''
  const builtAt = new Date().toISOString()

  const payload = {
    versionLabel: formatVersionLabel(semver, revision, subRevision),
    semver,
    revision,
    subRevision,
    commitHash,
    branch,
    dirty,
    builtAt,
    projectLabel: config.projectLabel,
  }

  const outPath = join(root, config.buildInfoRelativePath)
  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, `${JSON.stringify(payload, null, 2)}\n`)
  return payload
}
