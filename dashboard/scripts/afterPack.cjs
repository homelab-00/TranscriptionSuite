// electron-builder afterPack hook for Linux AppImage builds.
//
// 1. Removes chrome-sandbox — inside the squashfs mount it cannot have root
//    ownership / mode 4755, so Chromium's SUID sandbox check fatally aborts.
//
// 2. Wraps the Electron binary with a shell script that passes --no-sandbox.
//    On Ubuntu 23.10+ / Fedora GNOME, AppArmor blocks unprivileged user
//    namespaces, so the kernel namespace sandbox also fails. The flag must be
//    a real CLI argument — app.commandLine.appendSwitch() in the main script
//    runs too late (Chromium initialises the zygote before the JS executes).

const fs = require('fs');
const path = require('path');

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'linux') return;

  // --- 1. Remove chrome-sandbox (SUID not supported in AppImage) -----------
  const chromeSandbox = path.join(context.appOutDir, 'chrome-sandbox');
  if (fs.existsSync(chromeSandbox)) {
    fs.unlinkSync(chromeSandbox);
    console.log('  • removed chrome-sandbox (SUID not supported in AppImage)');
  }

  // --- 2. Wrap the Electron binary with --no-sandbox -----------------------
  const binaryName = context.packager.executableName;
  const binaryPath = path.join(context.appOutDir, binaryName);
  const renamedPath = binaryPath + '.bin';

  fs.renameSync(binaryPath, renamedPath);

  const wrapper = [
    '#!/bin/bash',
    `exec "\${BASH_SOURCE%/*}/${binaryName}.bin" --no-sandbox "$@"`,
    '',
  ].join('\n');

  fs.writeFileSync(binaryPath, wrapper, { mode: 0o755 });
  console.log(`  • wrapped ${binaryName} with --no-sandbox launcher`);
};
