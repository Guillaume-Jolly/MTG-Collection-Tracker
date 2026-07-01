#!/usr/bin/env node
/**
 * Lanceur dev générique REFERENCE — npm dev + dashboard monitoring + versions.
 */
import { spawn, exec, execSync } from 'node:child_process'
import { createServer } from 'node:http'
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  watchFile,
  writeFileSync,
} from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defaultAppUrl, dashboardUrl, readDevLauncherConfig } from './lib/config.mjs'
import { syncBuildInfo } from './lib/sync-build-info.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(__dirname, '..', '..')
const MAX_LOG_LINES = 400
const DASHBOARD_PATH = join(__dirname, 'dashboard.html')
const SESSION_DIR = join(__dirname, '.dev-session')
const SESSION_STATE_FILE = join(SESSION_DIR, 'state.json')
const DEV_LOG_FILE = join(SESSION_DIR, 'dev.log')
const REATTACH_ARG = '--reattach'

const config = readDevLauncherConfig(REPO_ROOT)
const DASHBOARD_PORT = config.dashboardPort

/** @type {import('node:child_process').ChildProcess | null} */
let devProcess = null
/** @type {import('node:child_process').ChildProcess | null} */
let buildProcess = null
/** @type {import('node:http').Server | null} */
let dashboardServer = null

let gameUrl = defaultAppUrl(config)
let devStatus = 'starting'
let startedAt = Date.now()
let openedAppOnce = false
let openedDashboardOnce = false
let launcherReattached = false
/** @type {number | null} */
let attachedDevPid = null
/** @type {string[]} */
let logLines = []
let devLogOffset = 0
/** @type {Record<string, unknown> | null} */
let lastBuildInfoSnapshot = null
/** @type {string | null} */
let lastBuildInfoKey = null
/** @type {ReturnType<typeof setTimeout> | null} */
let buildInfoWatchTimer = null
/** @type {ReturnType<typeof setInterval> | null} */
let attachedDevPollTimer = null

function ensureSessionDir() {
  mkdirSync(SESSION_DIR, { recursive: true })
}

function buildInfoFingerprint(info) {
  if (!info || typeof info !== 'object') return null
  return `${info.versionLabel ?? '?'}|${info.revision ?? '?'}|${info.subRevision ?? '?'}|${info.builtAt ?? '?'}`
}

function formatBuildInfoCapture(previous, next) {
  if (!next || typeof next !== 'object') return 'build-info mis à jour'
  const label = next.versionLabel ?? '?'
  const commit = next.commitHash ?? '?'
  const dirty = next.dirty ? ' · working tree sale' : ''
  if (!previous) return `Version captée : ${label} (${commit})${dirty}`
  if (previous.versionLabel !== next.versionLabel) {
    return `Version captée : ${previous.versionLabel ?? '?'} → ${label} (${commit})${dirty}`
  }
  return `Version captée : ${label} (${commit})${dirty}`
}

function buildInfoPath() {
  return join(REPO_ROOT, config.buildInfoRelativePath)
}

function handleBuildInfoDiskUpdate() {
  const next = readJson(buildInfoPath())
  const fingerprint = buildInfoFingerprint(next)
  if (!fingerprint || fingerprint === lastBuildInfoKey) return
  pushLog(formatBuildInfoCapture(lastBuildInfoSnapshot, next), 'launcher')
  lastBuildInfoSnapshot = next
  lastBuildInfoKey = fingerprint
}

function watchBuildInfoFile() {
  const path = buildInfoPath()
  if (!existsSync(path)) return
  const initial = readJson(path)
  if (initial) {
    lastBuildInfoSnapshot = initial
    lastBuildInfoKey = buildInfoFingerprint(initial)
  }
  watchFile(path, { interval: 1500 }, () => {
    if (buildInfoWatchTimer) clearTimeout(buildInfoWatchTimer)
    buildInfoWatchTimer = setTimeout(() => {
      buildInfoWatchTimer = null
      handleBuildInfoDiskUpdate()
    }, 250)
  })
}

function pushLog(line, source = 'dev') {
  const stamp = new Date().toLocaleTimeString('fr-FR', { hour12: false })
  logLines.push(`[${stamp}] [${source}] ${line}`)
  if (logLines.length > MAX_LOG_LINES) logLines = logLines.slice(-MAX_LOG_LINES)
}

function appendDevOutputLine(line, source = 'dev') {
  if (!line.trim()) return
  pushLog(line.trim(), source)
  ensureSessionDir()
  appendFileSync(DEV_LOG_FILE, `[${source}] ${line.trim()}\n`, 'utf8')
}

function resetDevLogFile() {
  ensureSessionDir()
  writeFileSync(DEV_LOG_FILE, '', 'utf8')
  devLogOffset = 0
}

function tailDevLogFile() {
  if (!existsSync(DEV_LOG_FILE)) return
  const content = readFileSync(DEV_LOG_FILE, 'utf8')
  if (content.length <= devLogOffset) return
  const chunk = content.slice(devLogOffset)
  devLogOffset = content.length
  for (const line of chunk.split(/\r?\n/)) {
    if (line.trim()) pushLog(line.trim(), 'dev')
  }
}

function initDevLogTail() {
  if (!existsSync(DEV_LOG_FILE)) {
    devLogOffset = 0
    return
  }
  devLogOffset = readFileSync(DEV_LOG_FILE, 'utf8').length
  watchFile(DEV_LOG_FILE, { interval: 500 }, tailDevLogFile)
}

function isProcessAlive(pid) {
  if (!pid || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

async function probeUrl(url) {
  try {
    const res = await fetch(url, { cache: 'no-store' })
    return res.ok
  } catch {
    return false
  }
}

function saveSessionState({ pendingReattach = false } = {}) {
  ensureSessionDir()
  writeFileSync(
    SESSION_STATE_FILE,
    `${JSON.stringify(
      {
        pendingReattach,
        devPid: devProcess?.pid ?? attachedDevPid,
        gameUrl,
        devStatus,
        startedAt,
        openedAppOnce,
        logs: logLines,
        lastBuildInfoSnapshot,
        lastBuildInfoKey,
        savedAt: Date.now(),
      },
      null,
      2,
    )}\n`,
  )
}

function loadSessionState() {
  if (!existsSync(SESSION_STATE_FILE)) return null
  try {
    return JSON.parse(readFileSync(SESSION_STATE_FILE, 'utf8'))
  } catch {
    return null
  }
}

function git(command) {
  try {
    return execSync(command, { cwd: REPO_ROOT, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function readJson(path) {
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

function readLocalBuildInfo() {
  const pkg = readJson(join(REPO_ROOT, 'package.json')) ?? {}
  return {
    packageVersion: pkg.version ?? '?',
    buildInfo: readJson(buildInfoPath()),
    revision: readJson(join(REPO_ROOT, config.revisionRelativePath)),
    branch: git('git rev-parse --abbrev-ref HEAD') || 'unknown',
    commit: git('git rev-parse --short HEAD') || 'unknown',
    dirty: git('git status --porcelain') !== '',
  }
}

async function fetchLiveBuildInfo(url) {
  try {
    const infoPath = `/${config.buildInfoRelativePath.replace(/^public\//, '')}`
    const res = await fetch(new URL(infoPath, url), { cache: 'no-store' })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

function openInBrowser(url) {
  const safeUrl = url.replace(/"/g, '')
  const browserExe = config.browserExecutable?.trim()
  if (browserExe) {
    spawn(browserExe, ['--new-tab', safeUrl], { shell: false, stdio: 'ignore', detached: true }).unref()
    return
  }
  const command =
    process.platform === 'win32'
      ? `start "" "${safeUrl}"`
      : process.platform === 'darwin'
        ? `open "${safeUrl}"`
        : `xdg-open "${safeUrl}"`
  exec(command, { shell: true })
}

function parseDevUrl(chunk) {
  const text = String(chunk)
  const localMatch =
    text.match(/Local:\s+(https?:\/\/[^\s]+)/i) ??
    text.match(/(https?:\/\/localhost:\d+\/?)/i) ??
    text.match(/(http:\/\/127\.0\.0\.1:\d+\/?)/i)
  if (localMatch?.[1]) {
    gameUrl = localMatch[1].endsWith('/') ? localMatch[1] : `${localMatch[1]}/`
  }
}

function stopProcessTree(child) {
  if (!child?.pid) return
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(child.pid), '/f', '/t'], { shell: true, stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }
}

function packageHasScript(name) {
  const pkg = readJson(join(REPO_ROOT, 'package.json'))
  return Boolean(pkg?.scripts?.[name])
}

function markRunningAndMaybeOpenApp(text) {
  if (
    devStatus === 'starting' &&
    (/ready in/i.test(text) ||
      /➜\s+Local:/i.test(text) ||
      /listening/i.test(text) ||
      /disponible sur/i.test(text) ||
      /Serving HTTP/i.test(text))
  ) {
    devStatus = 'running'
    if (!gameUrl.includes(String(config.devPort))) {
      gameUrl = defaultAppUrl(config)
    }
    if (config.openBrowserOnStart && !openedAppOnce) {
      openedAppOnce = true
      pushLog(`Ouverture app : ${gameUrl}`, 'launcher')
      setTimeout(() => openInBrowser(gameUrl), 400)
    }
  }
}

function startDevServer() {
  if (devProcess) {
    stopProcessTree(devProcess)
    devProcess = null
  }
  attachedDevPid = null
  if (attachedDevPollTimer) {
    clearInterval(attachedDevPollTimer)
    attachedDevPollTimer = null
  }

  devStatus = 'starting'
  startedAt = Date.now()
  openedAppOnce = false
  gameUrl = defaultAppUrl(config)
  resetDevLogFile()

  if (config.syncBuildInfoOnStart) {
    try {
      syncBuildInfo(REPO_ROOT, config)
      pushLog('build-info synchronisé', 'launcher')
    } catch (error) {
      pushLog(`sync build-info : ${error.message}`, 'launcher')
    }
  }

  if (!packageHasScript(config.devScript)) {
    pushLog(`Script npm "${config.devScript}" absent — démarrage manuel requis`, 'launcher')
    devStatus = 'stopped'
    return
  }

  pushLog(`Démarrage npm run ${config.devScript}…`, 'launcher')
  devProcess = spawn('npm', ['run', config.devScript], {
    cwd: REPO_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, FORCE_COLOR: '0' },
  })

  const onData = (chunk) => {
    const text = String(chunk)
    parseDevUrl(text)
    for (const line of text.split(/\r?\n/)) appendDevOutputLine(line)
    markRunningAndMaybeOpenApp(text)
  }

  devProcess.stdout?.on('data', onData)
  devProcess.stderr?.on('data', onData)
  devProcess.on('exit', (code, signal) => {
    pushLog(`Process dev terminé (code ${code ?? 'null'}, signal ${signal ?? 'null'})`, 'launcher')
    devProcess = null
    attachedDevPid = null
    if (devStatus !== 'stopping') devStatus = code === 0 ? 'stopped' : 'crashed'
    else devStatus = 'stopped'
  })
}

function stopDevServer() {
  devStatus = 'stopping'
  pushLog('Arrêt serveur dev…', 'launcher')
  stopProcessTree(devProcess)
  devProcess = null
  attachedDevPid = null
}

function restartDevServer() {
  pushLog('Redémarrage dev demandé…', 'launcher')
  stopDevServer()
  setTimeout(startDevServer, 800)
}

function restartLauncher() {
  saveSessionState({ pendingReattach: true })
  const child = spawn(process.execPath, [join(__dirname, 'server.mjs'), REATTACH_ARG], {
    cwd: REPO_ROOT,
    detached: true,
    stdio: 'ignore',
    env: process.env,
  })
  child.unref()
  dashboardServer?.close(() => process.exit(0))
  if (!dashboardServer) process.exit(0)
}

function runBuild() {
  if (buildProcess) {
    pushLog('Build déjà en cours', 'launcher')
    return
  }
  if (!packageHasScript(config.buildScript)) {
    pushLog(`Script "${config.buildScript}" absent`, 'launcher')
    return
  }
  pushLog(`npm run ${config.buildScript}…`, 'launcher')
  buildProcess = spawn('npm', ['run', config.buildScript], {
    cwd: REPO_ROOT,
    shell: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, FORCE_COLOR: '0' },
  })
  const pipe = (chunk, level) => {
    for (const line of String(chunk).split(/\r?\n/)) {
      if (line.trim()) pushLog(line.trim(), level)
    }
  }
  buildProcess.stdout?.on('data', (c) => pipe(c, 'build'))
  buildProcess.stderr?.on('data', (c) => pipe(c, 'build'))
  buildProcess.on('exit', (code) => {
    pushLog(`Build terminé (code ${code ?? 'null'})`, 'launcher')
    buildProcess = null
    if (config.syncBuildInfoOnStart) syncBuildInfo(REPO_ROOT, config)
  })
}

async function tryReattachSession() {
  const state = loadSessionState()
  if (!state?.pendingReattach) return false

  const pid = Number(state.devPid) || null
  const url = typeof state.gameUrl === 'string' ? state.gameUrl : gameUrl
  const pidAlive = pid ? isProcessAlive(pid) : false
  const serverAlive = await probeUrl(url)

  if (!pidAlive && !serverAlive) {
    pushLog('Reprise impossible — aucune session dev active', 'launcher')
    saveSessionState({ pendingReattach: false })
    return false
  }

  attachedDevPid = pidAlive ? pid : null
  gameUrl = url
  devStatus = 'running'
  startedAt = state.startedAt ?? Date.now()
  openedAppOnce = state.openedAppOnce ?? true
  logLines = Array.isArray(state.logs) ? state.logs.slice(-MAX_LOG_LINES) : []
  lastBuildInfoSnapshot = state.lastBuildInfoSnapshot ?? null
  lastBuildInfoKey = state.lastBuildInfoKey ?? null
  launcherReattached = true
  initDevLogTail()
  pushLog('Lanceur redémarré — session dev préservée', 'launcher')
  saveSessionState({ pendingReattach: false })
  return true
}

async function getStatusPayload() {
  const local = readLocalBuildInfo()
  const liveBuildInfo = devStatus === 'running' ? await fetchLiveBuildInfo(gameUrl) : null
  return {
    projectLabel: config.projectLabel,
    accentColor: config.accentColor,
    devStatus,
    gameUrl,
    dashboardUrl: dashboardUrl(config),
    uptimeMs: devStatus === 'running' ? Date.now() - startedAt : 0,
    pid: devProcess?.pid ?? attachedDevPid ?? null,
    buildRunning: Boolean(buildProcess),
    packageVersion: local.packageVersion,
    branch: local.branch,
    commit: local.commit,
    dirty: local.dirty,
    buildInfo: liveBuildInfo ?? local.buildInfo,
    revisionUpdatedAt: local.revision?.updatedAt ?? null,
    config: {
      devPort: config.devPort,
      dashboardPort: config.dashboardPort,
      devScript: config.devScript,
    },
    capabilities: {
      build: packageHasScript(config.buildScript),
      versionPrompt: packageHasScript('version:prompt'),
    },
    logCount: logLines.length,
    launcherReattached,
  }
}

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  })
  res.end(JSON.stringify(payload))
}

function readBody(req) {
  return new Promise((resolve) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => resolve(body))
  })
}

function createDashboardServer() {
  const dashboardHtml = readFileSync(DASHBOARD_PATH, 'utf8')
  return createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', dashboardUrl(config))
    const path = url.pathname

    if (path === '/' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(dashboardHtml)
      return
    }
    if (path === '/api/status' && req.method === 'GET') {
      sendJson(res, 200, await getStatusPayload())
      return
    }
    if (path === '/api/logs' && req.method === 'GET') {
      sendJson(res, 200, { lines: logLines })
      return
    }
    if (path === '/api/open-app' && req.method === 'POST') {
      openInBrowser(gameUrl)
      sendJson(res, 200, { ok: true, gameUrl })
      return
    }
    if (path === '/api/restart' && req.method === 'POST') {
      restartDevServer()
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/restart-launcher' && req.method === 'POST') {
      sendJson(res, 200, { ok: true })
      setTimeout(restartLauncher, 150)
      return
    }
    if (path === '/api/stop' && req.method === 'POST') {
      stopDevServer()
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/build' && req.method === 'POST') {
      runBuild()
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/clear-logs' && req.method === 'POST') {
      logLines = []
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/open-repo' && req.method === 'POST') {
      const folder = REPO_ROOT.replace(/"/g, '')
      const command =
        process.platform === 'win32'
          ? `start "" "${folder}"`
          : process.platform === 'darwin'
            ? `open "${folder}"`
            : `xdg-open "${folder}"`
      exec(command, { shell: true })
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/version-prompt' && req.method === 'POST') {
      if (packageHasScript('version:prompt')) {
        spawn('npm', ['run', 'version:prompt'], { cwd: REPO_ROOT, shell: true, stdio: 'ignore' })
        pushLog('npm run version:prompt lancé', 'launcher')
      }
      sendJson(res, 200, { ok: true })
      return
    }
    if (path === '/api/sync-build-info' && req.method === 'POST') {
      syncBuildInfo(REPO_ROOT, config)
      handleBuildInfoDiskUpdate()
      sendJson(res, 200, { ok: true })
      return
    }

    await readBody(req)
    sendJson(res, 404, { error: 'not-found' })
  })
}

function shutdown() {
  pushLog('Fermeture lanceur…', 'launcher')
  stopDevServer()
  stopProcessTree(buildProcess)
  if (attachedDevPollTimer) clearInterval(attachedDevPollTimer)
  process.exit(0)
}

function listenDashboard(server, { delayMs = 0 } = {}) {
  const startListening = () => {
    server.listen(DASHBOARD_PORT, '127.0.0.1', () => {
      const url = dashboardUrl(config)
      console.log(`[Dev Launcher] ${config.projectLabel} — dashboard : ${url}`)
      pushLog(`Dashboard prêt : ${url}`, 'launcher')
      if (config.openDashboardOnStart && !openedDashboardOnce) {
        openedDashboardOnce = true
        openInBrowser(url)
      }
    })
  }
  server.on('error', (error) => {
    if (error?.code === 'EADDRINUSE') {
      pushLog(`Port ${DASHBOARD_PORT} occupé — retry…`, 'launcher')
      setTimeout(() => server.close(() => startListening()), 500)
      return
    }
    console.error(error)
    process.exit(1)
  })
  if (delayMs > 0) setTimeout(startListening, delayMs)
  else startListening()
}

async function main() {
  if (!existsSync(join(REPO_ROOT, 'package.json'))) {
    console.error('Erreur : lancer depuis la racine du projet (package.json).')
    process.exit(1)
  }

  ensureSessionDir()
  const isReattach = process.argv.includes(REATTACH_ARG)
  let reattached = false
  if (isReattach) reattached = await tryReattachSession()

  dashboardServer = createDashboardServer()
  listenDashboard(dashboardServer, { delayMs: isReattach ? 700 : 0 })
  watchBuildInfoFile()

  if (!reattached) startDevServer()

  process.on('SIGINT', shutdown)
  process.on('SIGTERM', shutdown)
}

main()
