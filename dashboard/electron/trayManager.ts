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
  | 'idle' // Server stopped, no recording
  | 'active' // Server running, no session (original logo)
  | 'connecting' // WebSocket connecting
  | 'recording' // One-shot recording active
  | 'processing' // Transcription processing
  | 'live-listening' // Live mode listening
  | 'live-processing' // Live mode processing
  | 'muted' // Recording/live but muted
  | 'complete' // Transcription complete (reverts after 3s)
  | 'error' // Error state
  | 'disconnected'; // Server unreachable

export interface TrayMenuState {
  serverRunning: boolean;
  isRecording: boolean;
  isLive: boolean;
  isMuted: boolean;
  modelsLoaded: boolean;
  isLocalConnection: boolean;
  canCancel: boolean;
  isStandby: boolean;
}

// ─── Runtime Icon Generation ────────────────────────────────────────────────

interface RGB {
  r: number;
  g: number;
  b: number;
}

/** Vivid, maximally-distinct colors for each state's background area. */
const STATE_COLORS: Record<TrayState, RGB | null> = {
  idle: null, // grayscale only
  active: null, // original logo
  connecting: { r: 0xff, g: 0xd6, b: 0x00 }, // vivid yellow
  recording: { r: 0xf4, g: 0x43, b: 0x36 }, // red
  processing: { r: 0xff, g: 0x91, b: 0x00 }, // bright orange
  'live-listening': { r: 0x00, g: 0xe6, b: 0x76 }, // neon green
  'live-processing': { r: 0x00, g: 0xe5, b: 0xff }, // electric cyan
  muted: { r: 0x7c, g: 0x4d, b: 0xff }, // deep violet
  complete: { r: 0x29, g: 0x79, b: 0xff }, // bright blue
  error: { r: 0xff, g: 0x00, b: 0xff }, // magenta
  disconnected: null, // dimmed grayscale
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
  idle: 'TranscriptionSuite — Server stopped',
  active: 'TranscriptionSuite — Ready',
  connecting: 'TranscriptionSuite — Connecting…',
  recording: 'TranscriptionSuite — Recording',
  processing: 'TranscriptionSuite — Processing…',
  'live-listening': 'TranscriptionSuite — Live Mode',
  'live-processing': 'TranscriptionSuite — Live Processing…',
  muted: 'TranscriptionSuite — Muted',
  complete: 'TranscriptionSuite — Complete',
  error: 'TranscriptionSuite — Error',
  disconnected: 'TranscriptionSuite — Disconnected',
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
    modelsLoaded: true,
    isLocalConnection: true,
    canCancel: false,
    isStandby: false,
  };
  private completeTimer: ReturnType<typeof setTimeout> | null = null;
  private previousState: TrayState = 'idle';
  private isDev: boolean;
  private getWindow: () => BrowserWindow | null;

  /** Loaded once; used as source for all runtime tinting. */
  private baseIcon: Electron.NativeImage | null = null;

  /** Cache of generated tinted icons so we tint each state only once. */
  private iconCache = new Map<string, Electron.NativeImage>();

  /**
   * Dark desaturated green for "models unloaded" state —
   * matches v0.5.6's rgb(45, 140, 45) appearance.
   */
  private static readonly MODELS_UNLOADED_COLOR: RGB = { r: 0x2d, g: 0x8c, b: 0x2d };

  /** IPC callbacks — set via setActions() so main.ts controls Docker / renderer */
  private actions: {
    startServer?: () => Promise<void>;
    stopServer?: () => Promise<void>;
    startRecording?: () => void;
    stopRecording?: () => void;
    cancelRecording?: () => void;
    toggleMute?: () => void;
    transcribeFile?: () => void;
    startLiveMode?: () => void;
    stopLiveMode?: () => void;
    toggleLiveMute?: () => void;
    toggleModels?: () => void;
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

    // Left-click: only start a longform recording when in standby; do nothing otherwise
    this.tray.on('click', () => {
      if (this.menuState.isStandby && !this.menuState.isRecording && !this.menuState.isLive) {
        this.actions.startRecording?.();
      }
    });

    // Middle-click: only stop & transcribe a longform recording; do nothing otherwise
    this.tray.on('middle-click', () => {
      if (this.menuState.isRecording) {
        this.actions.stopRecording?.();
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
      // Don't save previousState — we'll let the renderer push the correct
      // post-completion state. The 3s timer just clears the 'complete' display
      // and falls back to 'active' (server should still be running after transcription).
      this.state = 'complete';
      this.applyState();

      this.completeTimer = setTimeout(() => {
        this.completeTimer = null;
        // Revert to 'active' (server is running) rather than the transient
        // 'processing' state that was active before completion.
        this.state = 'active';
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
   * An optional override color can be used for special cases (e.g. models unloaded).
   */
  private getIcon(state: TrayState, overrideColor?: RGB): Electron.NativeImage {
    const cacheKey = overrideColor
      ? `${state}:${overrideColor.r},${overrideColor.g},${overrideColor.b}`
      : state;
    const cached = this.iconCache.get(cacheKey);
    if (cached) return cached;
    const icon = this.generateIcon(state, overrideColor);
    this.iconCache.set(cacheKey, icon);
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
  private generateIcon(state: TrayState, overrideColor?: RGB): Electron.NativeImage {
    if (!this.baseIcon) return this.loadBaseIcon();

    // 'active' with no override → use the original unmodified logo
    if (state === 'active' && !overrideColor) return this.baseIcon;

    const { width, height } = this.baseIcon.getSize();
    const srcBitmap = this.baseIcon.toBitmap();
    const bitmap = Buffer.from(srcBitmap); // writable copy

    const color = overrideColor ?? STATE_COLORS[state];
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
        bitmap[i] = gray;
        bitmap[i + 1] = gray;
        bitmap[i + 2] = gray;
      } else if (color) {
        // Background pixel → tint with state color
        // Preserve depth by scaling color with relative brightness
        const factor = 0.6 + 0.4 * Math.min(lum / MIC_LUMINANCE_THRESHOLD, 1);
        bitmap[i] = Math.round(Math.min(color.b * factor, 255));
        bitmap[i + 1] = Math.round(Math.min(color.g * factor, 255));
        bitmap[i + 2] = Math.round(Math.min(color.r * factor, 255));
      } else {
        // null color (idle / disconnected) → plain grayscale
        const gray = Math.round(Math.min(lum * dimFactor, 255));
        bitmap[i] = gray;
        bitmap[i + 1] = gray;
        bitmap[i + 2] = gray;
      }
    }

    return nativeImage.createFromBitmap(bitmap, { width, height });
  }

  // ─── Internal ───────────────────────────────────────────────────────────

  private applyState(): void {
    if (!this.tray) return;
    // When models are unloaded but server is running, use dark green icon
    const useModelsUnloaded =
      !this.menuState.modelsLoaded &&
      this.menuState.serverRunning &&
      (this.state === 'active' || this.state === 'connecting');
    const icon = useModelsUnloaded
      ? this.getIcon(this.state, TrayManager.MODELS_UNLOADED_COLOR)
      : this.getIcon(this.state);
    this.tray.setImage(icon);
    this.tray.setToolTip(STATE_TOOLTIP_MAP[this.state]);
    this.rebuildMenu();
  }

  private rebuildMenu(): void {
    if (!this.tray) return;

    // On Linux, the AppIndicator/StatusNotifier tray may not update the
    // context menu unless we destroy and recreate it. Clear first.
    if (process.platform === 'linux') {
      this.tray.setContextMenu(null as unknown as Electron.Menu);
    }

    const {
      serverRunning,
      isRecording,
      isLive,
      isMuted,
      modelsLoaded,
      isLocalConnection,
      canCancel,
      isStandby,
    } = this.menuState;

    const win = this.getWindow();
    const windowVisible = win?.isVisible() ?? false;

    const template: Electron.MenuItemConstructorOptions[] = [];

    // ── Recording actions (match v0.5.6 order) ──────────────────────────

    template.push({
      label: 'Start Recording',
      enabled: isStandby && !isRecording && !isLive,
      click: () => this.actions.startRecording?.(),
    });

    template.push({
      label: 'Stop Recording',
      enabled: isRecording && !isLive,
      click: () => this.actions.stopRecording?.(),
    });

    template.push({
      label: 'Cancel',
      enabled: canCancel,
      click: () => this.actions.cancelRecording?.(),
    });

    template.push({ type: 'separator' });

    // ── File transcription ──────────────────────────────────────────────

    template.push({
      label: 'Transcribe File…',
      enabled: isStandby,
      click: () => this.actions.transcribeFile?.(),
    });

    template.push({ type: 'separator' });

    // ── Live Mode (v0.5.6: Start/Stop toggles label) ───────────────────

    template.push({
      label: isLive ? 'Stop Live Mode' : 'Start Live Mode',
      enabled: isStandby || isLive,
      click: () => {
        if (isLive) {
          this.actions.stopLiveMode?.();
        } else {
          this.actions.startLiveMode?.();
        }
      },
    });

    template.push({
      label: isMuted ? 'Unmute Live Mode' : 'Mute Live Mode',
      enabled: isLive,
      click: () => this.actions.toggleLiveMute?.(),
    });

    template.push({ type: 'separator' });

    // ── Model management (v0.5.6: local connection only) ────────────────

    template.push({
      label: modelsLoaded ? 'Unload All Models' : 'Reload Models',
      enabled: isStandby && isLocalConnection,
      click: () => this.actions.toggleModels?.(),
    });

    template.push({ type: 'separator' });

    // ── Show / Hide App ─────────────────────────────────────────────────

    template.push({
      label: windowVisible ? 'Hide App' : 'Show App',
      click: () => {
        const w = this.getWindow();
        if (!w) return;
        if (w.isVisible()) {
          w.hide();
        } else {
          w.show();
          w.focus();
        }
      },
    });

    template.push({ type: 'separator' });

    // ── Server control ──────────────────────────────────────────────────

    template.push(
      serverRunning
        ? {
            label: 'Stop Server',
            click: () => this.actions.stopServer?.(),
          }
        : {
            label: 'Start Server',
            click: () => this.actions.startServer?.(),
          },
    );

    template.push({ type: 'separator' });

    // ── Quit ────────────────────────────────────────────────────────────

    template.push({
      label: 'Quit',
      click: () => app.quit(),
    });

    this.tray.setContextMenu(Menu.buildFromTemplate(template));
  }
}
