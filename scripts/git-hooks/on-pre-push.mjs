/**
 * Git pre-push → bump B (main) ou C (branche feature).
 * Ne bloque jamais le push (exit 0).
 */
import { readFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

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
let branch = runGit(['rev-parse', '--abbrev-ref', 'HEAD'])

for (const line of raw.split('\n')) {
  const parts = line.trim().split(/\s+/)
  if (parts.length < 1) continue
  const localRef = parts[0]
  if (localRef.startsWith('refs/heads/')) {
    branch = localRef.slice('refs/heads/'.length)
    break
  }
}

process.env.GIT_BRANCH = branch

const script =
  mainBranches.has(branch) ? 'bump-main-push.mjs' : 'bump-branch-push.mjs'

const result = spawnSync(process.execPath, [join(root, 'scripts', script)], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
})

if (result.stdout) process.stdout.write(result.stdout)
if (result.stderr) process.stderr.write(result.stderr)

process.exit(0)
