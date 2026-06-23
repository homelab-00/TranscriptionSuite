// @vitest-environment node

/**
 * XDG desktop-file self-installation (electron/desktopIntegration.ts).
 *
 * The host portal's Registry.Register resolves "<app_id>.desktop" via GLib's
 * g_desktop_app_info_new() over the XDG applications path, so an AppImage must
 * install that file itself for Wayland global shortcuts to work. These tests
 * cover the pure builders and the guarded, idempotent install logic using an
 * in-memory filesystem — no real $HOME is touched and no live D-Bus is needed.
 */

import { describe, it, expect, vi } from 'vitest';
import {
  DESKTOP_FILE_NAME,
  applicationsDir,
  desktopFileTargetPath,
  quoteExecArg,
  buildDesktopFileContent,
  desktopFileMatchesAppImage,
  ensureDesktopFileInstalled,
} from '../desktopIntegration.js';
import { PORTAL_APP_ID } from '../waylandShortcuts.js';

const APPIMAGE = '/home/user/Apps/TranscriptionSuite-1.3.6.AppImage';

// ── In-memory filesystem double ───────────────────────────────────────────────

function makeFakeFs(initial: Record<string, string> = {}) {
  const files = new Map<string, string>(Object.entries(initial));
  const mkdirs: string[] = [];
  const writes: string[] = [];
  const removes: string[] = [];
  return {
    files,
    mkdirs,
    writes,
    removes,
    existsSync: (p: string) => files.has(p),
    readFileSync: (p: string, _enc: 'utf8') => {
      const v = files.get(p);
      if (v === undefined) throw new Error(`ENOENT: ${p}`);
      return v;
    },
    writeFileSync: (p: string, data: string, _opts: { mode: number }) => {
      files.set(p, data);
      writes.push(p);
    },
    mkdirSync: (p: string, _opts: { recursive: boolean }) => {
      mkdirs.push(p);
    },
    rmSync: (p: string, _opts: { force: boolean }) => {
      files.delete(p);
      removes.push(p);
    },
  };
}

const silentLogger = { log: () => {}, warn: () => {} };
const homedir = () => '/home/user';

function install(fakeFs: ReturnType<typeof makeFakeFs>, env: NodeJS.ProcessEnv) {
  return ensureDesktopFileInstalled({
    platform: 'linux',
    env,
    homedir,
    version: '1.3.6',
    fileSystem: fakeFs,
    logger: silentLogger,
  });
}

// ── Pure helpers ──────────────────────────────────────────────────────────────

describe('[P2] desktop file naming', () => {
  it('names the file exactly after the portal app id (load-bearing for portal lookup)', () => {
    expect(DESKTOP_FILE_NAME).toBe(`${PORTAL_APP_ID}.desktop`);
  });
});

describe('[P2] applicationsDir / desktopFileTargetPath', () => {
  it('falls back to ~/.local/share/applications', () => {
    expect(applicationsDir({}, homedir)).toBe('/home/user/.local/share/applications');
  });

  it('honors XDG_DATA_HOME when set', () => {
    expect(applicationsDir({ XDG_DATA_HOME: '/custom/data' }, homedir)).toBe(
      '/custom/data/applications',
    );
  });

  it('ignores an empty/whitespace XDG_DATA_HOME', () => {
    expect(applicationsDir({ XDG_DATA_HOME: '   ' }, homedir)).toBe(
      '/home/user/.local/share/applications',
    );
  });

  it('builds the full target path', () => {
    expect(desktopFileTargetPath({}, homedir)).toBe(
      `/home/user/.local/share/applications/${PORTAL_APP_ID}.desktop`,
    );
  });
});

describe('[P2] quoteExecArg', () => {
  it('double-quotes the path', () => {
    expect(quoteExecArg('/a/b/App.AppImage')).toBe('"/a/b/App.AppImage"');
  });

  it('escapes reserved characters (" ` $ \\)', () => {
    expect(quoteExecArg('/a/$x/`y`/"z"/\\w')).toBe('"/a/\\$x/\\`y\\`/\\"z\\"/\\\\w"');
  });
});

describe('[P2] buildDesktopFileContent', () => {
  const content = buildDesktopFileContent({ appImagePath: APPIMAGE, version: '1.3.6' });

  it('is a valid entry with the mandatory keys GLib requires', () => {
    expect(content.startsWith('[Desktop Entry]\n')).toBe(true);
    expect(content).toContain('Type=Application');
    expect(content).toContain('Name=TranscriptionSuite');
    expect(content).toContain(`Exec="${APPIMAGE}" %U`);
  });

  it('points TryExec at the raw AppImage path so it self-hides if moved', () => {
    expect(content).toContain(`TryExec=${APPIMAGE}`);
  });

  it('sets Icon and StartupWMClass to the app id', () => {
    expect(content).toContain(`Icon=${PORTAL_APP_ID}`);
    expect(content).toContain(`StartupWMClass=${PORTAL_APP_ID}`);
  });

  it('never sets Hidden=true (would make g_desktop_app_info_new return NULL)', () => {
    expect(content).not.toMatch(/Hidden\s*=\s*true/);
  });

  it('omits the version line when no version is supplied', () => {
    expect(buildDesktopFileContent({ appImagePath: APPIMAGE })).not.toContain('X-AppImage-Version');
  });
});

describe('[P2] desktopFileMatchesAppImage', () => {
  it('matches when TryExec points at the same AppImage', () => {
    const content = buildDesktopFileContent({ appImagePath: APPIMAGE });
    expect(desktopFileMatchesAppImage(content, APPIMAGE)).toBe(true);
  });

  it('does not match a different (older) AppImage path', () => {
    const content = buildDesktopFileContent({
      appImagePath: '/old/TranscriptionSuite-1.2.0.AppImage',
    });
    expect(desktopFileMatchesAppImage(content, APPIMAGE)).toBe(false);
  });
});

// ── ensureDesktopFileInstalled — guards ───────────────────────────────────────

describe('[P2] ensureDesktopFileInstalled — guards', () => {
  it('no-ops on non-linux platforms', () => {
    const fakeFs = makeFakeFs();
    const result = ensureDesktopFileInstalled({
      platform: 'darwin',
      env: { APPIMAGE },
      homedir,
      fileSystem: fakeFs,
      logger: silentLogger,
    });
    expect(result).toBe(false);
    expect(fakeFs.writes).toHaveLength(0);
  });

  it('no-ops when APPIMAGE is not set (dev / extracted run)', () => {
    const fakeFs = makeFakeFs();
    const result = ensureDesktopFileInstalled({
      platform: 'linux',
      env: {},
      homedir,
      fileSystem: fakeFs,
      logger: silentLogger,
    });
    expect(result).toBe(false);
    expect(fakeFs.writes).toHaveLength(0);
  });
});

// ── ensureDesktopFileInstalled — install / idempotency ────────────────────────

describe('[P2] ensureDesktopFileInstalled — install', () => {
  const target = `/home/user/.local/share/applications/${PORTAL_APP_ID}.desktop`;

  it('writes the desktop file pointing at $APPIMAGE on a clean system', () => {
    const fakeFs = makeFakeFs();
    const result = install(fakeFs, { APPIMAGE });

    expect(result).toBe(true);
    expect(fakeFs.writes).toContain(target);
    const written = fakeFs.files.get(target)!;
    expect(written).toContain(`Exec="${APPIMAGE}" %U`);
    expect(written).toContain(`TryExec=${APPIMAGE}`);
  });

  it('never writes the ephemeral /tmp/.mount_* path even if APPDIR is present', () => {
    const fakeFs = makeFakeFs();
    install(fakeFs, { APPIMAGE, APPDIR: '/tmp/.mount_Transc5Ofz9N' });
    expect(fakeFs.files.get(target)).not.toContain('/tmp/.mount_');
  });

  it('is idempotent: does not rewrite when the file already targets this AppImage', () => {
    const fakeFs = makeFakeFs({
      [target]: buildDesktopFileContent({ appImagePath: APPIMAGE, version: '1.3.6' }),
    });
    const result = install(fakeFs, { APPIMAGE });

    expect(result).toBe(true);
    expect(fakeFs.writes).toHaveLength(0);
  });

  it('rewrites when an existing file points at an older AppImage path', () => {
    const fakeFs = makeFakeFs({
      [target]: buildDesktopFileContent({
        appImagePath: '/old/TranscriptionSuite-1.2.0.AppImage',
      }),
    });
    const result = install(fakeFs, { APPIMAGE });

    expect(result).toBe(true);
    expect(fakeFs.writes).toContain(target);
    expect(fakeFs.files.get(target)).toContain(`TryExec=${APPIMAGE}`);
  });

  it('returns false and does not throw when the write fails (read-only HOME)', () => {
    const fakeFs = makeFakeFs();
    fakeFs.writeFileSync = () => {
      throw new Error('EROFS: read-only file system');
    };
    const warn = vi.fn();
    const result = ensureDesktopFileInstalled({
      platform: 'linux',
      env: { APPIMAGE },
      homedir,
      fileSystem: fakeFs,
      logger: { log: () => {}, warn },
    });

    expect(result).toBe(false);
    expect(warn).toHaveBeenCalledOnce();
  });
});

// ── ensureDesktopFileInstalled — stale file cleanup ───────────────────────────

describe('[P2] ensureDesktopFileInstalled — stale cleanup', () => {
  const staleTarget = '/home/user/.local/share/applications/transcriptionsuite.desktop';

  it('removes a stale v1.1.0 transcriptionsuite.desktop that is recognisably ours', () => {
    const fakeFs = makeFakeFs({
      [staleTarget]:
        '[Desktop Entry]\nName=TranscriptionSuite\nExec="/old/TranscriptionSuite-1.1.0.AppImage" %u\n',
    });
    install(fakeFs, { APPIMAGE });

    expect(fakeFs.removes).toContain(staleTarget);
    expect(fakeFs.files.has(staleTarget)).toBe(false);
  });

  it('leaves an unrelated transcriptionsuite.desktop untouched', () => {
    const unrelated = '[Desktop Entry]\nName=Some Other App\nExec=/usr/bin/other\n';
    const fakeFs = makeFakeFs({ [staleTarget]: unrelated });
    install(fakeFs, { APPIMAGE });

    expect(fakeFs.removes).not.toContain(staleTarget);
    expect(fakeFs.files.get(staleTarget)).toBe(unrelated);
  });
});
