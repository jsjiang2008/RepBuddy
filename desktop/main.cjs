// Start the private backend before opening the workout window.
const { app, BrowserWindow, dialog, session } = require('electron')
const { spawn } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const { join, resolve } = require('node:path')
const { mkdirSync, createWriteStream, writeFileSync } = require('node:fs')
const { createInterface } = require('node:readline')

app.setName('RepBuddy')
const smoke = process.argv.includes('--smoke-test')
const dataArgument = process.argv.find((argument) => argument.startsWith('--smoke-data='))
app.setPath('userData', smoke && dataArgument ? resolve(dataArgument.slice(13)) : join(app.getPath('appData'), 'RepBuddy'))
let backend
let window
let closing = false
let stopped = false
let output

// One desktop window owns the private database and camera at a time.
if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => { if (window) { window.restore(); window.focus() } })
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', (event) => {
    if (!backend || stopped) return
    event.preventDefault()
    if (closing) return
    closing = true
    window?.hide()
    backend.stdin.end()
    // Give pending saves and PostgreSQL time to shut down cleanly.
    const timer = setTimeout(() => backend.kill(), 45000)
    timer.unref()
  })
  app.whenReady().then(start).catch((error) => {
    if (smoke) writeFileSync(join(app.getPath('userData'), 'smoke-error.txt'), String(error))
    else dialog.showErrorBox('RepBuddy could not start', `Please restart the app. Details are in ${join(app.getPath('userData'), 'desktop.log')}.\n\n${error.message}`)
    app.quit()
  })
}

async function start() {
  const dataDir = app.getPath('userData')
  mkdirSync(dataDir, { recursive: true })
  output = createWriteStream(join(dataDir, 'desktop.log'), { flags: 'w' })
  const resources = app.isPackaged ? process.resourcesPath : join(__dirname, '..', 'build', 'desktop-resources')
  const token = randomBytes(32).toString('hex')
  const privateSession = session.fromPartition('repbuddy-desktop')
  privateSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  privateSession.setPermissionCheckHandler(() => false)
  window = new BrowserWindow({ width: 1360, height: 900, minWidth: 760, minHeight: 650,
    show: !smoke, backgroundColor: '#111512', title: 'RepBuddy',
    webPreferences: { session: privateSession, nodeIntegration: false, contextIsolation: true, sandbox: true },
  })
  window.removeMenu()
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  await window.loadFile(join(__dirname, 'loading.html'))
  const executable = join(resources, 'tracker', 'repbuddy-tracker.exe')
  backend = spawn(executable, ['--resources', resources, '--data-dir', dataDir, ...(smoke ? ['--check-model'] : [])], {
    windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], cwd: dataDir,
    env: { ...process.env, REPBUDDY_DESKTOP_TOKEN: token, PYTHON_DOTENV_DISABLED: '1' },
  })
  backend.stderr.pipe(output, { end: false })
  backend.stdin.on('error', () => {})
  backend.on('exit', (code) => {
    stopped = true
    output.end()
    if (!closing && window && !smoke) dialog.showErrorBox('Tracker stopped', 'Please reopen RepBuddy. Your completed workouts are saved.')
    if (closing || window) app.exit(smoke && code ? 1 : 0)
  })
  const port = await new Promise((resolvePort, reject) => {
    const timer = setTimeout(() => reject(new Error('The tracker took too long to start.')), 180000)
    const lines = createInterface({ input: backend.stdout })
    lines.on('line', (line) => {
      try {
        const message = JSON.parse(line)
        if (message.event === 'ready' && Number.isInteger(message.port) && message.port > 0 && message.port < 65536) {
          clearTimeout(timer)
          resolvePort(message.port)
        }
      } catch { output.write(`${line}\n`) }
    })
    backend.once('error', (error) => { clearTimeout(timer); stopped = true; reject(error) })
    backend.once('exit', () => { clearTimeout(timer); reject(new Error('The tracker could not finish startup.')) })
  })
  if (closing) return
  const origin = `http://127.0.0.1:${port}`
  privateSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const url = new URL(details.url)
    if (url.hostname !== '127.0.0.1' || url.port !== String(port) || !['http:', 'ws:'].includes(url.protocol)) {
      callback({ cancel: true })
      return
    }
    callback({ requestHeaders: { ...details.requestHeaders, 'X-RepBuddy-Token': token } })
  })
  privateSession.webRequest.onHeadersReceived((details, callback) => callback({ responseHeaders: {
    ...details.responseHeaders,
    'Content-Security-Policy': ["default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:" + port + "; object-src 'none'; frame-src 'none'; base-uri 'none'"],
  } }))
  window.webContents.on('will-navigate', (event, target) => { if (new URL(target).origin !== origin) event.preventDefault() })
  await window.loadURL(origin)
  if (!smoke) window.show()
  else {
    // Validate the packaged page and live connection without using a real camera.
    const result = await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
      const end = Date.now() + 15000;
      const timer = setInterval(() => {
        if (document.body.innerText.includes('Tracker connected')) {
          clearInterval(timer); resolve({ title: document.title, connected: true, settings: !!document.getElementById('workout-sets') });
        } else if (Date.now() > end) { clearInterval(timer); reject(new Error('Tracker did not connect')); }
      }, 100);
    })`)
    writeFileSync(join(dataDir, 'smoke-result.json'), JSON.stringify(result))
    const screenshot = await window.webContents.capturePage()
    writeFileSync(join(dataDir, 'smoke.png'), screenshot.toPNG())
    app.quit()
  }
}
