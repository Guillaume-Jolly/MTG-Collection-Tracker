#!/usr/bin/env node
/**
 * Smoke test infra REFERENCE — npm run validate:stack
 * Vérifie hooks, configs, DEV_LOG sans lancer le build complet.
 */
import { execSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readVersionConfig } from './lib/version-config.mjs'

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..')
const errors = []
const warnings = []

function ok(label) {
  console.log(`  ✓ ${label}`)
}

function fail(label, detail) {
  errors.push(`${label}: ${detail}`)
  console.error(`  ✗ ${label} — ${detail}`)
}

function warn(label, detail) {
  warnings.push(`${label}: ${detail}`)
  console.warn(`  ⚠ ${label} — ${detail}`)
}

function fileExists(relative, label = relative) {
  const path = join(root, relative)
  if (!existsSync(path)) {
    fail(label, 'introuvable')
    return false
  }
  ok(label)
  return true
}

function readJson(relative) {
  try {
    return JSON.parse(readFileSync(join(root, relative), 'utf8'))
  } catch {
    return null
  }
}

function gitConfig(key) {
  try {
    return execSync(`git config --get ${key}`, { cwd: root, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

console.log('[validate:stack] Infra REFERENCE\n')

if (!fileExists('package.json')) process.exit(1)

const pkg = readJson('package.json')
if (!pkg?.scripts?.['hooks:install']) {
  warn('package.json', 'script hooks:install absent')
} else {
  ok('package.json scripts hooks:install')
}

fileExists('.cursor/hooks.json')
fileExists('version.config.json')

const vcfg = readVersionConfig(root)
if (vcfg.devLogRelativePath) {
  fileExists(vcfg.devLogRelativePath.replace(/\\/g, '/'), 'DEV_LOG (version.config)')
}

fileExists('build-revision.json')

if (existsSync(join(root, 'dev-launcher.config.json'))) {
  ok('dev-launcher.config.json')
  fileExists('scripts/dev-launcher/server.mjs', 'scripts/dev-launcher/server.mjs')
} else {
  warn('dev-launcher', 'dev-launcher.config.json absent (optionnel)')
}

const hooksPath = gitConfig('core.hooksPath')
if (hooksPath === '.githooks') {
  ok('git core.hooksPath = .githooks')
} else if (!hooksPath) {
  fail('git hooks', 'core.hooksPath non configuré — npm run hooks:install')
} else {
  warn('git hooks', `core.hooksPath = ${hooksPath}`)
}

if (fileExists('.githooks/pre-push', 'githooks/pre-push')) {
  /* logged */
}

const hooksJson = readJson('.cursor/hooks.json')
if (hooksJson?.hooks) {
  const hasX = hooksJson.hooks.beforeSubmitPrompt?.length > 0
  const hasY = hooksJson.hooks.stop?.length > 0
  if (hasX && hasY) ok('Cursor hooks X/Y configurés')
  else fail('Cursor hooks', 'beforeSubmitPrompt ou stop manquant')
}

for (const script of ['version:prompt', 'version:task', 'dev:launcher']) {
  if (pkg?.scripts?.[script]) ok(`npm script ${script}`)
}

console.log('')
if (warnings.length) {
  console.log(`Avertissements : ${warnings.length}`)
}
if (errors.length) {
  console.error(`\n[validate:stack] ÉCHEC — ${errors.length} erreur(s)`)
  process.exit(1)
}
console.log('[validate:stack] OK')
