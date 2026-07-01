/**
 * Plugin Vite optionnel — sync public/build-info.json + route /build-info.json
 *
 * Usage (vite.config.ts) :
 *   import { syncBuildInfoPlugin } from './vite/sync-build-info.mjs'
 *   plugins: [syncBuildInfoPlugin({ projectLabel: 'Mon App' })]
 *
 * Prérequis : build-revision.json + package.json (stack REFERENCE)
 */
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..')

function runGit(command) {
  try {
    return execSync(command, { cwd: repoRoot, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function readRevision() {
  const path = join(repoRoot, 'build-revision.json')
  if (!existsSync(path)) return { revision: 1, subRevision: 0 }
  try {
    const raw = JSON.parse(readFileSync(path, 'utf8'))
    return {
      revision: typeof raw.revision === 'number' ? raw.revision : 1,
      subRevision: typeof raw.subRevision === 'number' ? raw.subRevision : 0,
    }
  } catch {
    return { revision: 1, subRevision: 0 }
  }
}

function formatLabel(semver, revision, subRevision) {
  const build = String(Math.max(0, revision)).padStart(2, '0')
  if (subRevision > 0) return `v${semver}.${build}.${subRevision}`
  return `v${semver}.${build}`
}

export function buildInfoPayload(projectLabel = 'app') {
  const pkg = JSON.parse(readFileSync(join(repoRoot, 'package.json'), 'utf8'))
  const semver = typeof pkg.version === 'string' ? pkg.version : '0.0.0'
  const { revision, subRevision } = readRevision()
  return {
    versionLabel: formatLabel(semver, revision, subRevision),
    semver,
    revision,
    subRevision,
    commitHash: runGit('git rev-parse --short HEAD') || 'unknown',
    branch: runGit('git rev-parse --abbrev-ref HEAD') || 'unknown',
    dirty: runGit('git status --porcelain') !== '',
    builtAt: new Date().toISOString(),
    projectLabel,
  }
}

export function writePublicBuildInfo(info, relativePath = 'public/build-info.json') {
  const out = join(repoRoot, relativePath)
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, `${JSON.stringify(info, null, 2)}\n`)
}

/**
 * @param {{ projectLabel?: string, buildInfoPath?: string, logPrefix?: string }} [options]
 */
export function syncBuildInfoPlugin(options = {}) {
  const label = options.projectLabel ?? 'app'
  const buildInfoPath = options.buildInfoPath ?? 'public/build-info.json'
  const prefix = options.logPrefix ?? `[${label}]`

  const sync = () => {
    const info = buildInfoPayload(label)
    writePublicBuildInfo(info, buildInfoPath)
    return info
  }

  return {
    name: 'reference-sync-build-info',
    config(_config, { command }) {
      const info = sync()
      if (command === 'serve') {
        console.log(`${prefix} Version : ${info.versionLabel}`)
      }
      return {
        define: {
          __APP_BUILD_INFO__: JSON.stringify(info),
        },
      }
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] !== '/build-info.json') {
          next()
          return
        }
        const info = buildInfoPayload(label)
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        res.setHeader('Cache-Control', 'no-store')
        res.end(JSON.stringify(info))
      })
    },
    buildStart() {
      const info = sync()
      console.log(`${prefix} Build ${info.versionLabel} (${info.commitHash})`)
    },
  }
}

export default syncBuildInfoPlugin
