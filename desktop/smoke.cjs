// Launch the packaged app with temporary history and verify that it shuts down.
const { spawn } = require('node:child_process')
const { existsSync, readFileSync, mkdirSync } = require('node:fs')
const { resolve, join } = require('node:path')
const data = resolve('build', `packaged-smoke-${Date.now()}`)
mkdirSync(data, { recursive: true })
const executable = resolve(process.argv[2] || 'release/win-unpacked/RepBuddy.exe')
if (!existsSync(executable)) throw new Error('Build the desktop app before running this check.')
const environment = { ...process.env }
delete environment.ELECTRON_RUN_AS_NODE
const child = spawn(executable, ['--smoke-test', `--smoke-data=${data}`], {
  env: environment, windowsHide: true, stdio: 'ignore',
})
const timer = setTimeout(() => { child.kill(); throw new Error(`Desktop check timed out. See ${data}`) }, 240000)
child.on('error', (error) => { clearTimeout(timer); throw error })
child.on('exit', (code) => {
  clearTimeout(timer)
  const marker = join(data, 'smoke-result.json')
  if (code !== 0 || !existsSync(marker)) throw new Error(`Desktop startup failed. See ${data}`)
  const result = JSON.parse(readFileSync(marker, 'utf8'))
  if (!result.connected || !result.settings) throw new Error('The packaged workout page did not connect.')
  if (existsSync(join(data, 'postgres-18', 'postmaster.pid'))) throw new Error('The private database did not stop.')
  console.log(`Packaged app connected and closed cleanly. Screenshot and logs in ${data}`)
})
