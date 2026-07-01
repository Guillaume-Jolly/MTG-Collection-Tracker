#!/usr/bin/env node
/**
 * A.B.C.X.Y - X update - prompt indent
 * Event Cursor : beforeSubmitPrompt
 */
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { logVersionHook, peekVersionHookProject } from '../../scripts/lib/version-hook-log.mjs'
import {
  enrichHookPayload,
  VERSION_HOOK_X_NAME,
} from '../../scripts/lib/version-hook-output.mjs'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

function readPromptFromStdin() {
  try {
    const raw = readFileSync(0, 'utf8')
    if (!raw.trim()) return ''
    const json = JSON.parse(raw)
    for (const key of ['prompt', 'text', 'userMessage', 'user_message', 'message', 'content']) {
      const value = json[key]
      if (typeof value === 'string' && value.trim()) return value
    }
    return ''
  } catch {
    return ''
  }
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`)
}

const prompt = readPromptFromStdin()
let versionHook = { hookName: VERSION_HOOK_X_NAME, started: peekVersionHookProject(root) }

if (/même\s*X|meme\s*X|same\s*X/i.test(prompt)) {
  versionHook = logVersionHook(root, {
    hook: 'beforeSubmitPrompt',
    hookName: VERSION_HOOK_X_NAME,
    action: 'skip',
    reason: 'opt-out même X',
  })
  emit(enrichHookPayload(root, VERSION_HOOK_X_NAME, versionHook, { continue: true }))
  process.exit(0)
}

const result = spawnSync(process.execPath, [join(root, 'scripts', 'bump-prompt.mjs')], {
  cwd: root,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
})

if (result.status !== 0) {
  versionHook = logVersionHook(root, {
    hook: 'beforeSubmitPrompt',
    hookName: VERSION_HOOK_X_NAME,
    action: 'skip',
    reason: 'bump-prompt failed',
    error: (result.stderr || '').trim() || null,
  })
} else {
  const line = (result.stdout || '').trim().split('\n').pop() || ''
  const labelMatch = line.match(/→\s*(v[\d.]+)/)
  versionHook = logVersionHook(root, {
    hook: 'beforeSubmitPrompt',
    hookName: VERSION_HOOK_X_NAME,
    action: 'bump-x',
    versionLabel: labelMatch?.[1] ?? (line || undefined),
  })
}

emit(enrichHookPayload(root, VERSION_HOOK_X_NAME, versionHook, { continue: true }))
process.exit(0)
