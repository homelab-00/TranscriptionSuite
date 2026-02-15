/**
 * Electron-builder afterSign hook for macOS notarization.
 *
 * Requires the following environment variables:
 *   APPLE_ID            — Apple Developer account email
 *   APPLE_APP_PASSWORD  — App-specific password (not your account password)
 *   APPLE_TEAM_ID       — Apple Developer Team ID (10-char alphanumeric)
 *
 * These are typically injected via GitHub Actions secrets.
 * The hook is a no-op when the variables are missing (local unsigned builds).
 */
const { notarize } = require('@electron/notarize');

exports.default = async function notarizing(context) {
  const { electronPlatformName, appOutDir } = context;

  // Only notarize macOS builds
  if (electronPlatformName !== 'darwin') {
    return;
  }

  // Skip if credentials are not configured (local dev builds)
  if (!process.env.APPLE_ID || !process.env.APPLE_APP_PASSWORD || !process.env.APPLE_TEAM_ID) {
    console.log('⚠ Skipping notarization: APPLE_ID / APPLE_APP_PASSWORD / APPLE_TEAM_ID not set.');
    return;
  }

  const appName = context.packager.appInfo.productFilename;
  const appPath = `${appOutDir}/${appName}.app`;

  console.log(`→ Notarizing ${appPath} …`);

  await notarize({
    appPath,
    appleId: process.env.APPLE_ID,
    appleIdPassword: process.env.APPLE_APP_PASSWORD,
    teamId: process.env.APPLE_TEAM_ID,
  });

  console.log('✓ Notarization complete.');
};
