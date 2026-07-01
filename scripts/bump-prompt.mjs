/**
 * Nouveau prompt utilisateur → révision +1 (npm run version:prompt).
 */
import { execSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { appendDevLogOpenSection } from './lib/dev-log-open-section.mjs'
import { projectLabel } from './lib/version-config.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const revisionPath = join(root, 'build-revision.json')
const publicBuildInfoPath = join(root, 'public/build-info.json')

function runGit(command) {
  try {
    return execSync(command, { cwd: root, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function getWorktreeFingerprint() {
  const head = runGit('git rev-parse HEAD') || 'unknown'
  const status = runGit('git status --porcelain')
  const diff = runGit('git diff HEAD')
  const untracked = runGit('git ls-files --others --exclude-standard')
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

function readState() {
  if (!existsSync(revisionPath)) return null
  try {
    const raw = JSON.parse(readFileSync(revisionPath, 'utf8'))
    if (typeof raw.revision !== 'number') return null
    return raw
  } catch {
    return null
  }
}

function initialRevision() {
  const commitCount = Number.parseInt(runGit('git rev-list --count HEAD') || '0', 10)
  const dirty = runGit('git status --porcelain') !== ''
  return dirty ? Math.max(1, commitCount) + 1 : Math.max(1, commitCount)
}

const existing = readState()
const revision = existing ? existing.revision + 1 : initialRevision()
const subRevision = 0
const fingerprint = getWorktreeFingerprint()

writeFileSync(
  revisionPath,
  `${JSON.stringify({ revision, subRevision, fingerprint, updatedAt: new Date().toISOString() }, null, 2)}\n`,
)

const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const semver = typeof pkg.version === 'string' ? pkg.version : '0.0.0'
const build = String(revision).padStart(2, '0')
const versionLabel = `v${semver}.${build}`

const buildInfo = {
  semver,
  commitCount: Number.parseInt(runGit('git rev-list --count HEAD') || '0', 10),
  commitHash: runGit('git rev-parse --short HEAD') || 'unknown',
  dirty: runGit('git status --porcelain') !== '',
  revision,
  subRevision,
  build,
  versionLabel,
  builtAt: new Date().toISOString(),
}

mkdirSync(dirname(publicBuildInfoPath), { recursive: true })
writeFileSync(publicBuildInfoPath, `${JSON.stringify(buildInfo, null, 2)}\n`)

appendDevLogOpenSection(root, revision, versionLabel)

console.log(`[${projectLabel(root)}] Prompt → ${versionLabel}`)
