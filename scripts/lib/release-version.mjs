/**
 * A.B.C release semver — package.json version (A=major, B=minor, C=patch).
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

export function parseSemver(version) {
  const match = String(version).trim().match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!match) {
    return { major: 0, minor: 0, patch: 0, raw: String(version) }
  }
  return {
    major: Number.parseInt(match[1], 10),
    minor: Number.parseInt(match[2], 10),
    patch: Number.parseInt(match[3], 10),
    raw: `${match[1]}.${match[2]}.${match[3]}`,
  }
}

export function formatSemver({ major, minor, patch }) {
  return `${major}.${minor}.${patch}`
}

export function readPackageJson(root) {
  return JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
}

export function readReleaseSemver(root) {
  const pkg = readPackageJson(root)
  return parseSemver(pkg.version ?? '0.0.0')
}

export function writeReleaseSemver(root, next) {
  const pkg = readPackageJson(root)
  const before = parseSemver(pkg.version ?? '0.0.0')
  pkg.version = formatSemver(next)
  writeFileSync(join(root, 'package.json'), `${JSON.stringify(pkg, null, 2)}\n`)
  return { before, after: next }
}

/** @param {'A'|'B'|'C'} segment */
export function bumpReleaseSegment(current, segment) {
  if (segment === 'A') {
    return { major: current.major + 1, minor: 0, patch: 0, segment: 'A' }
  }
  if (segment === 'B') {
    return { major: current.major, minor: current.minor + 1, patch: 0, segment: 'B' }
  }
  return { major: current.major, minor: current.minor, patch: current.patch + 1, segment: 'C' }
}

export function syncBuildInfoSemver(root) {
  const buildInfoPath = join(root, 'public/build-info.json')
  try {
    const pkg = readPackageJson(root)
    const semver = typeof pkg.version === 'string' ? pkg.version : '0.0.0'
    let buildInfo = {}
    try {
      buildInfo = JSON.parse(readFileSync(buildInfoPath, 'utf8'))
    } catch {
      /* fresh */
    }
    buildInfo.semver = semver
    buildInfo.builtAt = new Date().toISOString()
    writeFileSync(buildInfoPath, `${JSON.stringify(buildInfo, null, 2)}\n`)
  } catch {
    /* public/ may be absent in CI */
  }
}
