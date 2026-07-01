/**
 * Installe les git hooks projet : core.hooksPath=.githooks
 * npm run hooks:install
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const hooksDir = join(root, '.githooks')

if (!existsSync(join(hooksDir, 'pre-push'))) {
  console.error('[hooks:install] .githooks/pre-push introuvable')
  process.exit(1)
}

const result = spawnSync('git', ['config', 'core.hooksPath', '.githooks'], {
  cwd: root,
  encoding: 'utf8',
  stdio: 'inherit',
})

if (result.status !== 0) {
  process.exit(result.status ?? 1)
}

console.log('[hooks:install] core.hooksPath=.githooks')
console.log('[hooks:install] pre-push → bump B (main) ou C (branche)')
