/**
 * Lit dev-launcher.config.json à la racine du projet.
 */
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const DEFAULTS = {
  projectLabel: 'Dev Project',
  dashboardPort: 9221,
  devHost: '127.0.0.1',
  devPort: 5173,
  devScript: 'dev',
  buildScript: 'build',
  buildInfoRelativePath: 'public/build-info.json',
  revisionRelativePath: 'build-revision.json',
  openBrowserOnStart: true,
  openDashboardOnStart: true,
  syncBuildInfoOnStart: true,
  accentColor: '#7eb8ff',
  browserExecutable: '',
}

export function readDevLauncherConfig(root) {
  const path = join(root, 'dev-launcher.config.json')
  let file = {}
  if (existsSync(path)) {
    try {
      file = JSON.parse(readFileSync(path, 'utf8'))
    } catch {
      file = {}
    }
  }

  const envDashboard = process.env.DEV_LAUNCHER_DASHBOARD_PORT
  const envDevPort = process.env.DEV_LAUNCHER_DEV_PORT

  const config = { ...DEFAULTS, ...file }
  if (envDashboard) {
    const n = Number.parseInt(envDashboard, 10)
    if (!Number.isNaN(n)) config.dashboardPort = n
  }
  if (envDevPort) {
    const n = Number.parseInt(envDevPort, 10)
    if (!Number.isNaN(n)) config.devPort = n
  }
  return config
}

export function defaultAppUrl(config) {
  return `http://${config.devHost}:${config.devPort}/`
}

export function dashboardUrl(config) {
  return `http://127.0.0.1:${config.dashboardPort}/`
}
