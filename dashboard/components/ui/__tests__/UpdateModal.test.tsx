/**
 * UpdateModal — unit tests.
 *
 * Coverage lives across two suites:
 *   • `deriveBadgeContent` — pure mapper from CompatResult → verdict badge.
 *     Every row of the I/O matrix's "verdict" column.
 *   • `<UpdateModal>` component — I/O matrix rows driving DOM assertions:
 *     compatible / incompatible local / incompatible remote / unknown,
 *     release-notes present vs null, Update-Server-First pull success +
 *     failure, lifecycle (open/close/reopen), external-link rewiring.
 *
 * Mocking style matches UpdateBanner.test.tsx (globalThis.electronAPI
 * harness), and `sonner` is mocked at module scope.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from 'sonner';
import { UpdateModal, deriveBadgeContent } from '../UpdateModal';

// ── Harness ────────────────────────────────────────────────────────────────

interface ModalHarness {
  checkCompatibility: ReturnType<typeof vi.fn>;
  getStatus: ReturnType<typeof vi.fn>;
  pullImage: ReturnType<typeof vi.fn>;
  openExternal: ReturnType<typeof vi.fn>;
}

function buildHarness(): ModalHarness {
  return {
    checkCompatibility: vi.fn(),
    getStatus: vi.fn(),
    pullImage: vi.fn(),
    openExternal: vi.fn().mockResolvedValue(undefined),
  };
}

function install(
  h: ModalHarness,
  options: {
    appVersion?: string;
    releaseNotes?: string | null;
    serverLatest?: string | null;
    /** M7: when provided, exposes `app.getPlatform()` returning this value. Default omitted (renders as 'unknown'). */
    platform?: string;
  } = {},
): void {
  const appVersion = options.appVersion ?? '1.3.2';
  const releaseNotes = options.releaseNotes === undefined ? null : options.releaseNotes;
  const serverLatest = options.serverLatest === undefined ? null : options.serverLatest;
  const status = {
    lastChecked: new Date().toISOString(),
    app: {
      current: appVersion,
      latest: '1.3.3',
      updateAvailable: true,
      error: null,
      releaseNotes,
    },
    server: {
      current: null,
      latest: serverLatest,
      updateAvailable: false,
      error: null,
      releaseNotes: null,
    },
  };
  h.getStatus.mockResolvedValue(status);
  const appBridge: Record<string, unknown> = { openExternal: h.openExternal };
  if (options.platform !== undefined) {
    appBridge.getPlatform = () => options.platform as string;
  }
  (window as unknown as { electronAPI: Record<string, unknown> }).electronAPI = {
    updates: {
      checkCompatibility: h.checkCompatibility,
      getStatus: h.getStatus,
    },
    docker: { pullImage: h.pullImage },
    app: appBridge,
  };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.error).mockClear();
});

afterEach(() => {
  cleanup();
  delete (window as unknown as { electronAPI?: unknown }).electronAPI;
});

// ── deriveBadgeContent (pure) ──────────────────────────────────────────────

describe('deriveBadgeContent', () => {
  it('returns pending tone while compat is null or pending=true', () => {
    expect(deriveBadgeContent(null, false).tone).toBe('pending');
    expect(deriveBadgeContent(null, true).tone).toBe('pending');
  });

  it('returns green + version for compatible result', () => {
    const content = deriveBadgeContent(
      {
        result: 'compatible',
        manifest: {
          version: '1.3.3',
          compatibleServerRange: '>=1.0.0',
          sha256: {},
          releaseType: 'stable',
        },
        serverVersion: '1.4.2',
      },
      false,
    );
    expect(content.tone).toBe('green');
    expect(content.text).toContain('v1.4.2');
  });

  it('returns amber + local tail on incompatible + local', () => {
    const content = deriveBadgeContent(
      {
        result: 'incompatible',
        manifest: {
          version: '1.3.3',
          compatibleServerRange: '>=1.5.0',
          sha256: {},
          releaseType: 'stable',
        },
        serverVersion: '1.0.0',
        compatibleRange: '>=1.5.0',
        deployment: 'local',
      },
      false,
    );
    expect(content.tone).toBe('amber');
    expect(content.text).toContain('update server first');
  });

  it('returns amber + remote tail on incompatible + remote', () => {
    const content = deriveBadgeContent(
      {
        result: 'incompatible',
        manifest: {
          version: '1.3.3',
          compatibleServerRange: '>=1.5.0',
          sha256: {},
          releaseType: 'stable',
        },
        serverVersion: '1.0.0',
        compatibleRange: '>=1.5.0',
        deployment: 'remote',
      },
      false,
    );
    expect(content.tone).toBe('amber');
    expect(content.text).toContain('update your remote server manually');
  });

  it('returns slate + reason on unknown', () => {
    const content = deriveBadgeContent(
      { result: 'unknown', reason: 'server-version-unavailable' },
      false,
    );
    expect(content.tone).toBe('slate');
    expect(content.text).toContain('server-version-unavailable');
  });
});

// ── Component ──────────────────────────────────────────────────────────────

describe('<UpdateModal>', () => {
  it('renders nothing when isOpen=false on first mount', () => {
    const h = buildHarness();
    install(h);
    const { container } = render(
      <UpdateModal
        isOpen={false}
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('happy path (compatible + release notes): renders markdown, enables Install Dashboard, fires onConfirmInstall + onClose', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    install(h, { releaseNotes: '## What changed\n\n- Fixed **everything**' });

    const onClose = vi.fn();
    const onConfirmInstall = vi.fn();

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={onConfirmInstall}
      />,
    );
    await flush();
    await flush();

    // Markdown renders (headings + bold)
    const notes = screen.getByTestId('release-notes');
    expect(notes.textContent).toContain('What changed');
    expect(notes.querySelector('strong')?.textContent).toBe('everything');

    const installBtn = screen.getByRole('button', { name: /install dashboard/i });
    expect((installBtn as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(installBtn);
    expect(onConfirmInstall).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('incompatible + local: disables Install Dashboard and shows Update Server First button', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'incompatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.5.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.0.0',
      compatibleRange: '>=1.5.0',
      deployment: 'local',
    });
    install(h, { serverLatest: '1.5.0' });

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const installBtn = screen.getByRole('button', { name: /install dashboard/i });
    expect((installBtn as HTMLButtonElement).disabled).toBe(true);

    const serverFirstBtn = screen.getByRole('button', { name: /update server first/i });
    expect(serverFirstBtn).toBeTruthy();
  });

  it('incompatible + remote: hides Update Server First and disables Install', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'incompatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.5.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.0.0',
      compatibleRange: '>=1.5.0',
      deployment: 'remote',
    });
    install(h);

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    expect(
      (screen.getByRole('button', { name: /install dashboard/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.queryByRole('button', { name: /update server first/i })).toBeNull();
  });

  it('unknown compat: fail-open — Install Dashboard enabled, Update Server First hidden', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'unknown',
      reason: 'server-version-unavailable',
    });
    install(h);

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const installBtn = screen.getByRole('button', { name: /install dashboard/i });
    expect((installBtn as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole('button', { name: /update server first/i })).toBeNull();
  });

  it('release notes absent: shows fallback text, does NOT invoke markdown renderer', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    install(h, { releaseNotes: null });

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const notes = screen.getByTestId('release-notes');
    expect(notes.textContent).toContain('No release notes published');
    // Markdown-specific elements (headings, strong) should not be present.
    expect(notes.querySelector('strong')).toBeNull();
    expect(notes.querySelector('h3')).toBeNull();
  });

  it('Update Server First success: calls docker.pullImage, toasts restart instruction, re-checks compat, keeps modal open', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'incompatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.5.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.0.0',
      compatibleRange: '>=1.5.0',
      deployment: 'local',
    });
    h.pullImage.mockResolvedValue('pulled');
    install(h, { serverLatest: '1.5.0' });

    const onClose = vi.fn();

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /update server first/i }));
    await flush();
    await flush();

    expect(h.pullImage).toHaveBeenCalledTimes(1);
    expect(h.pullImage).toHaveBeenCalledWith('1.5.0');
    expect(vi.mocked(toast.success).mock.calls[0]?.[0]).toMatch(/Restart the server/);
    // Modal stayed open (onClose NOT called) + compat re-fetched.
    expect(onClose).not.toHaveBeenCalled();
    expect(h.checkCompatibility).toHaveBeenCalledTimes(2);
  });

  it('Update Server First failure: toasts error, modal stays open, no pull-image re-entry', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'incompatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.5.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.0.0',
      compatibleRange: '>=1.5.0',
      deployment: 'local',
    });
    h.pullImage.mockRejectedValue(new Error('network unreachable'));
    install(h, { serverLatest: '1.5.0' });

    const onClose = vi.fn();

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /update server first/i }));
    await flush();
    await flush();

    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).toMatch(/network unreachable/);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Update Server First with unknown server tag: toasts error, does NOT call pullImage', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'incompatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.5.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.0.0',
      compatibleRange: '>=1.5.0',
      deployment: 'local',
    });
    install(h, { serverLatest: null });

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /update server first/i }));
    await flush();

    expect(h.pullImage).not.toHaveBeenCalled();
    expect(vi.mocked(toast.error).mock.calls[0]?.[0]).toMatch(/tag unavailable/);
  });

  it('compat fetch pending: disables confirm buttons while spinner shows', async () => {
    const h = buildHarness();
    // Never-resolving promise — keep pending state for the assertion.
    h.checkCompatibility.mockReturnValue(new Promise(() => {}));
    install(h);

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();

    expect(screen.getByRole('status', { name: /server compatibility/i }).textContent).toMatch(
      /Checking server compatibility/,
    );
    expect(
      (screen.getByRole('button', { name: /install dashboard/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('compat fetch throws: degrades to unknown and fail-opens Install Dashboard', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockRejectedValue(new Error('ipc crashed'));
    install(h);

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const installBtn = screen.getByRole('button', { name: /install dashboard/i });
    await waitFor(() => {
      expect((installBtn as HTMLButtonElement).disabled).toBe(false);
    });
    expect(screen.getByRole('status', { name: /server compatibility/i }).textContent).toMatch(
      /Could not verify/,
    );
  });

  it('reopen refetches compat + release notes', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'unknown',
      reason: 'no-manifest',
    });
    install(h);

    const { rerender } = render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    rerender(
      <UpdateModal
        isOpen={false}
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();

    rerender(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    expect(h.checkCompatibility.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(h.getStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('Cancel button closes modal (onClose called)', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'unknown',
      reason: 'no-manifest',
    });
    install(h);

    const onClose = vi.fn();

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('external link in release notes routes through app.openExternal (no renderer navigation)', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    install(h, { releaseNotes: '[docs](https://example.invalid/changelog)' });

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const anchor = screen.getByRole('link', { name: 'docs' }) as HTMLAnchorElement;
    const clickEvent = new MouseEvent('click', { bubbles: true, cancelable: true });
    anchor.dispatchEvent(clickEvent);

    expect(clickEvent.defaultPrevented).toBe(true);
    expect(h.openExternal).toHaveBeenCalledWith('https://example.invalid/changelog');
  });

  it('dangerous-protocol links in release notes are blocked from app.openExternal', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    // Release body with a javascript: URL — an attacker-influenceable channel
    // (anyone with push to the releases page can publish release bodies).
    install(h, {
      releaseNotes: '[evil](javascript:alert(1))\n\n[local](file:///etc/passwd)',
    });

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={() => {}}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();
    await flush();

    const links = screen.queryAllByRole('link');
    for (const anchor of links) {
      const clickEvent = new MouseEvent('click', { bubbles: true, cancelable: true });
      anchor.dispatchEvent(clickEvent);
      expect(clickEvent.defaultPrevented).toBe(true);
    }
    expect(h.openExternal).not.toHaveBeenCalled();
  });

  it('double-click on Install Dashboard fires onConfirmInstall at most once', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'compatible',
      manifest: {
        version: '1.3.3',
        compatibleServerRange: '>=1.0.0',
        sha256: {},
        releaseType: 'stable',
      },
      serverVersion: '1.4.2',
    });
    install(h);

    const onClose = vi.fn();
    const onConfirmInstall = vi.fn();

    render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={onConfirmInstall}
      />,
    );
    await flush();
    await flush();

    const installBtn = screen.getByRole('button', { name: /install dashboard/i });
    fireEvent.click(installBtn);
    fireEvent.click(installBtn);
    fireEvent.click(installBtn);

    expect(onConfirmInstall).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('backdrop click closes modal', async () => {
    const h = buildHarness();
    h.checkCompatibility.mockResolvedValue({
      result: 'unknown',
      reason: 'no-manifest',
    });
    install(h);

    const onClose = vi.fn();

    const { container } = render(
      <UpdateModal
        isOpen
        targetVersion="1.3.3"
        currentVersion="1.3.2"
        onClose={onClose}
        onConfirmInstall={() => {}}
      />,
    );
    await flush();

    // Backdrop is the first absolute-positioned div inside the dialog.
    const backdrop = container.querySelector('div[aria-modal="true"] > div.absolute');
    expect(backdrop).toBeTruthy();
    fireEvent.click(backdrop as Element);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ── M7: Windows SmartScreen heads-up callout ─────────────────────────────

  describe('M7: SmartScreen callout', () => {
    function renderCompatible(platform?: string) {
      const h = buildHarness();
      h.checkCompatibility.mockResolvedValue({
        result: 'compatible',
        manifest: {
          version: '1.3.3',
          compatibleServerRange: '>=1.0.0',
          sha256: {},
          releaseType: 'stable',
        },
        serverVersion: '1.4.2',
      });
      install(h, { platform });
      render(
        <UpdateModal
          isOpen
          targetVersion="1.3.3"
          currentVersion="1.3.2"
          onClose={() => {}}
          onConfirmInstall={() => {}}
        />,
      );
      return h;
    }

    it('renders the SmartScreen callout when getPlatform() returns "win32"', async () => {
      renderCompatible('win32');
      await flush();
      const callout = screen.getByTestId('smartscreen-callout');
      expect(callout).toBeInTheDocument();
      expect(callout.textContent).toMatch(/SmartScreen/);
      expect(callout.textContent).toMatch(/More info/);
      expect(callout.textContent).toMatch(/Run anyway/);
    });

    it('does NOT render the callout on linux', async () => {
      renderCompatible('linux');
      await flush();
      expect(screen.queryByTestId('smartscreen-callout')).not.toBeInTheDocument();
    });

    it('does NOT render the callout on darwin', async () => {
      renderCompatible('darwin');
      await flush();
      expect(screen.queryByTestId('smartscreen-callout')).not.toBeInTheDocument();
    });

    it('does NOT render the callout when getPlatform is not exposed (defaults to unknown)', async () => {
      renderCompatible(undefined);
      await flush();
      expect(screen.queryByTestId('smartscreen-callout')).not.toBeInTheDocument();
    });
  });
});
