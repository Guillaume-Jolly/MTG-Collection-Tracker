/**
 * Journal local des bumps A/B/C (git push / MEP).
 */
import { appendFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { formatSemver } from './release-version.mjs'

const LOG_REL = join('docs', 'traceability', 'changelog', 'release-events.jsonl')

export function appendReleaseEvent(root, event) {
  const path = join(root, LOG_REL)
  mkdirSync(dirname(path), { recursive: true })
  appendFileSync(path, `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`)
}

export function formatReleaseMessage({ segment, reason, before, after, dryRun }) {
  const prefix = dryRun ? '[release:dry-run]' : '[release]'
  return `${prefix} ${reason} → ${segment} ${formatSemver(before)} → ${formatSemver(after)}`
}
