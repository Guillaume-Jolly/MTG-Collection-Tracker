/**
 * Logique pre-push : bump B/C seulement si le commit poussé n'inclut pas déjà le bump.
 */
import { spawnSync } from 'node:child_process'
import {
  bumpReleaseSegment,
  formatSemver,
  parseSemver,
} from './release-version.mjs'

const ZERO_SHA = '0'.repeat(40)

function runGit(root, args) {
  const result = spawnSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  if (result.status !== 0) return ''
  return (result.stdout || '').trim()
}

export function readPackageVersionAtRef(root, ref) {
  if (!ref || ref === ZERO_SHA) return null
  const raw = runGit(root, ['show', `${ref}:package.json`])
  if (!raw) return null
  try {
    return parseSemver(JSON.parse(raw).version ?? '0.0.0')
  } catch {
    return null
  }
}

export function semverCompare(a, b) {
  if (a.major !== b.major) return a.major - b.major
  if (a.minor !== b.minor) return a.minor - b.minor
  return a.patch - b.patch
}

/**
 * @param {'B'|'C'} segment
 */
export function shouldSkipReleaseBump({ remoteVersion, localVersion, segment }) {
  if (!remoteVersion || !localVersion) return { skip: false, reason: null }

  const expected = bumpReleaseSegment(remoteVersion, segment)
  const localStr = formatSemver(localVersion)
  const expectedStr = formatSemver(expected)

  if (localStr === expectedStr) {
    return { skip: true, reason: `commit déjà à ${expectedStr} (remote ${formatSemver(remoteVersion)})` }
  }

  if (semverCompare(localVersion, expected) > 0) {
    return {
      skip: true,
      reason: `semver local ${localStr} déjà au-dessus du bump ${segment} attendu (${expectedStr})`,
    }
  }

  return { skip: false, reason: null }
}

export function parsePrePushStdin(raw) {
  const lines = []
  for (const line of raw.split('\n')) {
    const parts = line.trim().split(/\s+/)
    if (parts.length < 4) continue
    const [localRef, localSha, remoteRef, remoteSha] = parts
    lines.push({ localRef, localSha, remoteRef, remoteSha })
  }
  return lines
}

export function branchNameFromPushLine(line, fallbackBranch) {
  if (line?.localRef?.startsWith('refs/heads/')) {
    return line.localRef.slice('refs/heads/'.length)
  }
  return fallbackBranch
}
