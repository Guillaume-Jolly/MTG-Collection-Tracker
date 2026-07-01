/**
 * Bump B — push main (minor semver).
 * npm run version:main-push
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
const after = bumpReleaseSegment(before, 'B')

if (dryRun) {
  console.log(formatReleaseMessage({ segment: 'B', reason: 'push main', before, after, dryRun: true }))
  process.exit(0)
}

writeReleaseSemver(root, after)
syncBuildInfoSemver(root)
appendReleaseEvent(root, {
  segment: 'B',
  trigger: 'main-push',
  before: formatSemver(before),
  after: formatSemver(after),
})

console.log(formatReleaseMessage({ segment: 'B', reason: 'push main', before, after, dryRun: false }))
console.log('[release] Pense à : DEV_LOG recap, pipelines, kickoff phase si clôture.')
