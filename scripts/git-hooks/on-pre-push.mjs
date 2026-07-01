/**
 * Git pre-push → bump B (main) ou C (branche feature).
 * Ne bump pas si le commit poussé inclut déjà le semver attendu (évite double-bump).
 * Ne bloque jamais le push (exit 0).
 */
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  branchNameFromPushLine,
  parsePrePushStdin,
  readPackageVersionAtRef,
  shouldSkipReleaseBump,
} from '../lib/pre-push-release.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function runGit(args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' })
  return (result.stdout || '').trim()
}

function readStdin() {
  try {
    return readFileSync(0, 'utf8').trim()
  } catch {
    return ''
  }
}

const raw = readStdin()
if (!raw) process.exit(0)

const mainBranches = new Set(['main', 'master'])
const pushLines = parsePrePushStdin(raw)
const headBranch = runGit(['rev-parse', '--abbrev-ref', 'HEAD'])
const branch = pushLines.length
  ? branchNameFromPushLine(pushLines[0], headBranch)
  : headBranch

const segment = mainBranches.has(branch) ? 'B' : 'C'
const script = mainBranches.has(branch) ? 'bump-main-push.mjs' : 'bump-branch-push.mjs'

const line = pushLines[0]
if (line && line.remoteSha && line.localSha) {
  const remoteVersion = readPackageVersionAtRef(root, line.remoteSha)
  const localVersion = readPackageVersionAtRef(root, line.localSha)
  const decision = shouldSkipReleaseBump({ remoteVersion, localVersion, segment })

  if (decision.skip) {
    console.log(`[release] skip ${segment} (${branch}) — ${decision.reason}`)
    process.exit(0)
  }
}

process.env.GIT_BRANCH = branch

const result = spawnSync(process.execPath, [join(root, 'scripts', script)], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
})

if (result.stdout) process.stdout.write(result.stdout)
if (result.stderr) process.stderr.write(result.stderr)

process.exit(0)
