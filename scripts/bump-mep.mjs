/**
 * Bump A — MEP (major semver). Manuel + validation humaine.
 * npm run version:mep [--dry-run]
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
const after = bumpReleaseSegment(before, 'A')

if (dryRun) {
  console.log(formatReleaseMessage({ segment: 'A', reason: 'MEP', before, after, dryRun: true }))
  console.log('[release:dry-run] Étapes humaines :')
  console.log('  1. Tag git (ex. v' + formatSemver(after) + '.0)')
  console.log('  2. Entrée docs/traceability/changelog/VERSION-INDEX.md')
  console.log('  3. Deploy appli associée')
  console.log('  4. Relancer sans --dry-run si OK')
  process.exit(0)
}

writeReleaseSemver(root, after)
syncBuildInfoSemver(root)
appendReleaseEvent(root, {
  segment: 'A',
  trigger: 'mep',
  before: formatSemver(before),
  after: formatSemver(after),
})

console.log(formatReleaseMessage({ segment: 'A', reason: 'MEP', before, after, dryRun: false }))
console.log('[release] MEP enregistrée — compléter VERSION-INDEX + tag + deploy.')
