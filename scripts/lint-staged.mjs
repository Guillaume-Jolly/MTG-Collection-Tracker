#!/usr/bin/env node
/**
 * Lint ESLint sur fichiers git staged uniquement (optionnel, pre-commit).
 * Skip silencieux si eslint absent ou aucun fichier staged éligible.
 */
import { execSync, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')

function stagedFiles() {
  try {
    const out = execSync('git diff --cached --name-only --diff-filter=ACMR', {
      cwd: root,
      encoding: 'utf8',
    })
    return out
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .filter((f) => /\.(mjs|cjs|js|ts|tsx|jsx|vue)$/.test(f))
  } catch {
    return []
  }
}

const eslintBin = join(root, 'node_modules', 'eslint', 'bin', 'eslint.js')
if (!existsSync(eslintBin)) {
  process.exit(0)
}

const files = stagedFiles()
if (files.length === 0) {
  process.exit(0)
}

console.log(`[lint-staged] ${files.length} fichier(s)`)
const result = spawnSync(process.execPath, [eslintBin, ...files, '--max-warnings=0'], {
  cwd: root,
  stdio: 'inherit',
})
process.exit(result.status ?? 1)
