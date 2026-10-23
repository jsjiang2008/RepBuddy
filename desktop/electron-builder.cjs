// Package the interface, Python tracker, and private PostgreSQL runtime together.
module.exports = {
  appId: 'com.repbuddy.desktop',
  productName: 'RepBuddy',
  directories: { output: 'release' },
  files: ['desktop/main.cjs', 'desktop/loading.html', 'package.json'],
  extraResources: [{ from: 'build/desktop-resources', to: '.', filter: ['**/*'] }],
  asar: true,
  npmRebuild: false,
  win: { target: [{ target: 'nsis', arch: ['x64'] }], icon: 'desktop/icon.ico',
    artifactName: 'RepBuddy-Setup-${version}-${arch}.${ext}', signExecutable: false },
  nsis: { oneClick: false, perMachine: false, allowElevation: false,
    allowToChangeInstallationDirectory: true, createDesktopShortcut: true,
    createStartMenuShortcut: true, deleteAppDataOnUninstall: false, runAfterFinish: false },
}
