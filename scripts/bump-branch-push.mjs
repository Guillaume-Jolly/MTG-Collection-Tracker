/**
 * Bump C — push branche feature (patch semver).
 * npm run version:branch-push
 */
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { appendReleaseEvent, formatReleaseMessage } from './lib/release-bump-log.mjs'
import {
  bumpReleaseSegment,
  formatSemver,
  readReleaseSemver,
  syncBuildInfoSemver,
  writeReleaseSemver,
} from './lib/release-version.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const dryRun = process.argv.includes('--dry-run')

const before = readReleaseSemver(root)
const after = bumpReleaseSegment(before, 'C')

if (dryRun) {
  console.log(formatReleaseMessage({ segment: 'C', reason: 'push branche', before, after, dryRun: true }))
  process.exit(0)
}

writeReleaseSemver(root, after)
syncBuildInfoSemver(root)
appendReleaseEvent(root, {
  segment: 'C',
  trigger: 'branch-push',
  before: formatSemver(before),
  after: formatSemver(after),
  branch: process.env.GIT_BRANCH ?? null,
})

console.log(formatReleaseMessage({ segment: 'C', reason: 'push branche', before, after, dryRun: false }))
