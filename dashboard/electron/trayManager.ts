/**
 * TrayManager — system tray with state-aware icons generated at runtime,
 * dynamic context menu, and IPC bridge to the renderer process.
 *
 * Icons are produced by tinting the base logo PNG at runtime:
 *  • 'active' → original logo (no modification)
 *  • 'idle' / 'disconnected' → grayscale conversion (disconnected dimmed)
 *  • All others → grayscale mic symbol + state-colored background area
 *
 * The renderer pushes state updates via IPC; the tray manager resolves the
 * correct icon, tooltip, and context menu items automatically.
 */

import { Tray, Menu, nativeImage, app, BrowserWindow } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Tray State Enum ────────────────────────────────────────────────────────

export type TrayState =
  | 'idle'            // Server stopped, no recording
  | 'active'          // Server running, no session (original logo)
  | 'connecting'      // WebSocket connecting
  | 'recording'       // One-shot recording active
  | 'processing'      // Transcription processing
  | 'live-listening'  // Live mode listening
  | 'live-processing' // Live mode processing
  | 'muted'           // Recording/live but muted
  | 'complete'        // Transcription complete (reverts after 3s)
  | 'error'           // Error state
  | 'disconnected';   // Server unreachable

export interface TrayMenuState {
  serverRunning: boolean;
  isRecording: boolean;
  isLive: boolean;
  isMuted: boolean;
}

// ─── Runtime Icon Generation ────────────────────────────────────────────────

interface RGB { r: number; g: number; b: number }

/** Vivid, maximally-distinct colors for each state's background area. */
const STATE_COLORS: Record<TrayState, RGB | null> = {
  'idle':            null,                           // grayscale only
  'active':          null,                           // original logo
  'connecting':      { r: 0xFF, g: 0xD6, b: 0x00 }, // vivid yellow
  'recording':       { r: 0xF4, g: 0x43, b: 0x36 }, // red
  'processing':      { r: 0xFF, g: 0x91, b: 0x00 }, // bright orange
  'live-listening':  { r: 0x00, g: 0xE6, b: 0x76 }, // neon green
  'live-processing': { r: 0x00, g: 0xE5, b: 0xFF }, // electric cyan
  'muted':           { r: 0x7C, g: 0x4D, b: 0xFF }, // deep violet
  'complete':        { r: 0x29, g: 0x79, b: 0xFF }, // bright blue
  'error':           { r: 0xFF, g: 0x00, b: 0xFF }, // magenta
  'disconnected':    null,                           // dimmed grayscale
};

/**
 * Luminance threshold separating "microphone symbol" (bright, > threshold)
 * from "background area" (darker, ≤ threshold).
 *
 * Derived from histogram analysis of the base logo:
 *   • Background gradient pixels: luminance ~110–165
 *   • Mic symbol pixels:          luminance ~219–245
 *   • Gap between them:           166–218
 */
const MIC_LUMINANCE_THRESHOLD = 190;

const STATE_TOOLTIP_MAP: Record<TrayState, string> = {
  'idle':            'TranscriptionSuite — Server stopped',
  'active':          'TranscriptionSuite — Ready',
  'connecting':      'TranscriptionSuite — Connecting…',
  'recording':       'TranscriptionSuite — Recording',
  'processing':      'TranscriptionSuite — Processing…',
  'live-listening':  'TranscriptionSuite — Live Mode',
  'live-processing': 'TranscriptionSuite — Live Processing…',
  'muted':           'TranscriptionSuite — Muted',
  'complete':        'TranscriptionSuite — Complete',
  'error':           'TranscriptionSuite — Error',
  'disconnected':    'TranscriptionSuite — Disconnected',
};

// ─── TrayManager Class ──────────────────────────────────────────────────────

export class TrayManager {
  private tray: Tray | null = null;
  private state: TrayState = 'idle';
  private menuState: TrayMenuState = {
    serverRunning: false,
    isRecording: false,
    isLive: false,
    isMuted: false,
  };
  private completeTimer: ReturnType<typeof setTimeout> | null = null;
  private previousState: TrayState = 'idle';
  private isDev: boolean;
  private getWindow: () => BrowserWindow | null;

  /** Loaded once; used as source for all runtime tinting. */
  private baseIcon: Electron.NativeImage | null = null;

  /** Cache of generated tinted icons so we tint each state only once. */
  private iconCache = new Map<TrayState, Electron.NativeImage>();

  /** IPC callbacks — set via setActions() so main.ts controls Docker / renderer */
  private actions: {
    startServer?: () => Promise<void>;
    stopServer?: () => Promise<void>;
    startRecording?: () => void;
    stopRecording?: () => void;
    toggleMute?: () => void;
    transcribeFile?: () => void;
  } = {};

  constructor(isDev: boolean, getWindow: () => BrowserWindow | null) {
    this.isDev = isDev;
    this.getWindow = getWindow;
  }

  /** Wire up action callbacks (called from main.ts after window creation) */
  setActions(actions: typeof this.actions): void {
    this.actions = actions;
  }

  /** Create the tray icon. Call once during app.whenReady(). */
  create(): void {
    this.baseIcon = this.loadBaseIcon();
    const icon = this.getIcon(this.state);
    this.tray = new Tray(icon);
    this.tray.setToolTip(STATE_TOOLTIP_MAP[this.state]);
    this.rebuildMenu();

    this.tray.on('click', () => {
      const win = this.getWindow();
      if (win) {
        if (win.isVisible()) {
          win.hide();
        } else {
          win.show();
          win.focus();
        }
      }
    });
  }

  /** Destroy the tray (called on app quit). */
  destroy(): void {
    if (this.completeTimer) clearTimeout(this.completeTimer);
    this.tray?.destroy();
    this.tray = null;
  }

  setState(newState: TrayState): void {
    if (newState === this.state) return;

    if (this.completeTimer) {
      clearTimeout(this.completeTimer);
      this.completeTimer = null;
    }

    if (newState === 'complete') {
      this.previousState = this.state;
      this.state = 'complete';
      this.applyState();

      this.completeTimer = setTimeout(() => {
        this.completeTimer = null;
        this.state = this.previousState;
        this.applyState();
      }, 3000);
    } else {
      this.state = newState;
      this.applyState();
    }
  }

  setMenuState(menuState: Partial<TrayMenuState>): void {
    this.menuState = { ...this.menuState, ...menuState };
    this.rebuildMenu();
  }

  setTooltip(tooltip: string): void {
    this.tray?.setToolTip(tooltip);
  }

  getState(): TrayState {
    return this.state;
  }

  // ─── Icon Generation ───────────────────────────────────────────────────

  private loadBaseIcon(): Electron.NativeImage {
    const iconPath = this.isDev
      ? path.join(__dirname, '../../build/assets/tray-icon.png')
      : path.join(process.resourcesPath, 'tray-icon.png');
    return nativeImage.createFromPath(iconPath);
  }

  /**
   * Get (or lazily generate) the icon for a tray state.
   * Icons are cached after first generation.
   */
  private getIcon(state: TrayState): Electron.NativeImage {
    const cached = this.iconCache.get(state);
    if (cached) return cached;
    const icon = this.generateIcon(state);
    this.iconCache.set(state, icon);
    return icon;
  }

  /**
   * Generate a tinted icon from the base logo at runtime.
   *
   * Algorithm:
   *  1. For each pixel, compute perceived luminance (ITU-R BT.601).
   *  2. Pixels above MIC_LUMINANCE_THRESHOLD → mic symbol → grayscale.
   *  3. Pixels at or below threshold → background → tint with state color.
   *  4. Transparent pixels are left untouched.
   *
   * Electron's nativeImage.toBitmap() returns raw pixels in BGRA format
   * (Chromium/Skia kBGRA_8888 on all platforms).
   */
  private generateIcon(state: TrayState): Electron.NativeImage {
    if (!this.baseIcon) return this.loadBaseIcon();

    // 'active' → use the original unmodified logo
    if (state === 'active') return this.baseIcon;

    const { width, height } = this.baseIcon.getSize();
    const srcBitmap = this.baseIcon.toBitmap();
    const bitmap = Buffer.from(srcBitmap); // writable copy

    const color = STATE_COLORS[state];
    const dimFactor = state === 'disconnected' ? 0.4 : 1.0;

    for (let i = 0; i < bitmap.length; i += 4) {
      // BGRA byte order
      const b = bitmap[i];
      const g = bitmap[i + 1];
      const r = bitmap[i + 2];
      const a = bitmap[i + 3];

      if (a < 10) continue; // skip transparent

      const lum = 0.299 * r + 0.587 * g + 0.114 * b;

      if (lum > MIC_LUMINANCE_THRESHOLD) {
        // Bright pixel → mic symbol → grayscale
        const gray = Math.round(Math.min(lum * dimFactor, 255));
        bitmap[i]     = gray;
        bitmap[i + 1] = gray;
        bitmap[i + 2] = gray;
      } else if (color) {
        // Background pixel → tint with state color
        // Preserve depth by scaling color with relative brightness
        const factor = 0.6 + 0.4 * Math.min(lum / MIC_LUMINANCE_THRESHOLD, 1);
        bitmap[i]     = Math.round(Math.min(color.b * factor, 255));
        bitmap[i + 1] = Math.round(Math.min(color.g * factor, 255));
        bitmap[i + 2] = Math.round(Math.min(color.r * factor, 255));
      } else {
        // null color (idle / disconnected) → plain grayscale
        const gray = Math.round(Math.min(lum * dimFactor, 255));
        bitmap[i]     = gray;
        bitmap[i + 1] = gray;
        bitmap[i + 2] = gray;
      }
    }

    return nativeImage.createFromBitmap(bitmap, { width, height });
  }

  // ─── Internal ───────────────────────────────────────────────────────────

  private applyState(): void {
    if (!this.tray) return;
    this.tray.setImage(this.getIcon(this.state));
    this.tray.setToolTip(STATE_TOOLTIP_MAP[this.state]);
    this.rebuildMenu();
  }

  private rebuildMenu(): void {
    if (!this.tray) return;

    const win = this.getWindow();
    const windowVisible = win?.isVisible() ?? false;

    const template: Electron.MenuItemConstructorOptions[] = [
      {
        label: windowVisible ? 'Hide Window' : 'Show Window',
        click: () => {
          const w = this.getWindow();
          if (!w) return;
          if (w.isVisible()) { w.hide(); }
          else { w.show(); w.focus(); }
        },
      },
      { type: 'separator' },

      ...(this.menuState.serverRunning
        ? [{ label: 'Stop Server', click: () => { this.actions.stopServer?.(); } } as Electron.MenuItemConstructorOptions]
        : [{ label: 'Start Server', click: () => { this.actions.startServer?.(); } } as Electron.MenuItemConstructorOptions]
      ),

      ...(this.menuState.serverRunning ? [
        { type: 'separator' as const },
        ...(this.menuState.isRecording || this.menuState.isLive
          ? [
              {
                label: this.menuState.isLive ? 'Stop Live Mode' : 'Stop Recording',
                click: () => { this.actions.stopRecording?.(); },
              } as Electron.MenuItemConstructorOptions,
              {
                label: this.menuState.isMuted ? 'Unmute' : 'Mute',
                click: () => { this.actions.toggleMute?.(); },
              } as Electron.MenuItemConstructorOptions,
            ]
          : [
              {
                label: 'Start Recording',
                click: () => { this.actions.startRecording?.(); },
              } as Electron.MenuItemConstructorOptions,
            ]
        ),
        { type: 'separator' as const },
        {
          label: 'Transcribe File…',
          click: () => { this.actions.transcribeFile?.(); },
        } as Electron.MenuItemConstructorOptions,
      ] : []),

      { type: 'separator' },
      { label: 'Quit', click: () => { app.quit(); } },
    ];

    this.tray.setContextMenu(Menu.buildFromTemplate(template));
  }
}
