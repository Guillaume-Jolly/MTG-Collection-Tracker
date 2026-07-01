#!/usr/bin/env node
/**
 * Git pre-commit — validate:stack + lint staged (optionnel).
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function run(label, script) {
  const path = join(root, script)
  if (!existsSync(path)) return 0
  const result = spawnSync(process.execPath, [path], { cwd: root, stdio: 'inherit' })
  if (result.status !== 0) {
    console.error(`[pre-commit] ${label} failed`)
    return result.status ?? 1
  }
  return 0
}

const v = run('validate:stack', 'scripts/validate-stack.mjs')
if (v !== 0) process.exit(v)

const l = run('lint-staged', 'scripts/lint-staged.mjs')
process.exit(l)
