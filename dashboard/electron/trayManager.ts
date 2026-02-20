/**
 * TrayManager — system tray with state-aware icons generated at runtime,
 * dynamic context menu, and IPC bridge to the renderer process.
 *
 * Icons are produced by tinting the base logo PNG at runtime:
 *  • 'idle' → original logo (no modification, server running & healthy)
 *  • 'disconnected' → grayscale + dimmed
 *  • 'models-unloaded' → desaturated + dimmed original
 *  • 'error' → red background + black X overlay
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
  | 'idle' // Server running, healthy, nothing active (original logo)
  | 'recording' // Long-form recording in progress
  | 'processing' // Transcription in progress (any type)
  | 'complete' // Transcription finished (white flash → revert to idle)
  | 'live-active' // Live mode on, unmuted
  | 'recording-muted' // Recording but muted
  | 'live-muted' // Live mode on, muted
  | 'uploading' // File upload/import in progress
  | 'models-unloaded' // Server running but models unloaded
  | 'error' // Server reports error (red + black X)
  | 'disconnected'; // Server not running / unreachable

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
  idle: null, // original logo (no tint)
  recording: { r: 0xff, g: 0xd6, b: 0x00 }, // yellow #FFD600
  processing: { r: 0xff, g: 0x91, b: 0x00 }, // orange #FF9100
  complete: { r: 0xff, g: 0xff, b: 0xff }, // white flash
  'live-active': { r: 0xf4, g: 0x43, b: 0x36 }, // red #F44336
  'recording-muted': { r: 0x80, g: 0x6b, b: 0x00 }, // dimmed yellow (~0.5 brightness)
  'live-muted': { r: 0x80, g: 0x00, b: 0x00 }, // maroon #800000
  uploading: { r: 0x29, g: 0x79, b: 0xff }, // blue #2979FF
  'models-unloaded': null, // special handling (desaturated + dimmed)
  error: { r: 0xd3, g: 0x2f, b: 0x2f }, // red #D32F2F
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
  idle: 'TranscriptionSuite — Ready',
  recording: 'TranscriptionSuite — Recording',
  processing: 'TranscriptionSuite — Processing…',
  complete: 'TranscriptionSuite — Complete',
  'live-active': 'TranscriptionSuite — Live Mode',
  'recording-muted': 'TranscriptionSuite — Recording (Muted)',
  'live-muted': 'TranscriptionSuite — Live Mode (Muted)',
  uploading: 'TranscriptionSuite — Uploading…',
  'models-unloaded': 'TranscriptionSuite — Models Unloaded',
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
  private isDev: boolean;
  private getWindow: () => BrowserWindow | null;

  /** Loaded once; used as source for all runtime tinting. */
  private baseIcon: Electron.NativeImage | null = null;

  /** Cache of generated tinted icons so we tint each state only once. */
  private iconCache = new Map<string, Electron.NativeImage>();

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

    // Left-click: toggle recording — start if standby, stop & transcribe if recording.
    // On Linux (AppIndicator/StatusNotifier) middle-click is not supported,
    // so left-click acts as a toggle to cover both actions.
    this.tray.on('click', () => {
      if (this.menuState.isRecording && !this.menuState.isLive) {
        this.actions.stopRecording?.();
      } else if (
        this.menuState.isStandby &&
        !this.menuState.isRecording &&
        !this.menuState.isLive
      ) {
        this.actions.startRecording?.();
      }
    });

    // Middle-click: stop & transcribe (works on Windows/macOS; no-op on Linux AppIndicator)
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
      this.state = 'complete';
      this.applyState();

      this.completeTimer = setTimeout(() => {
        this.completeTimer = null;
        // Revert to 'idle' (server is running & healthy) after the white flash.
        this.state = 'idle';
        this.applyState();
      }, 500);
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

  /** Rebuild the context menu to reflect current window visibility. */
  notifyWindowVisibilityChanged(): void {
    this.rebuildMenu();
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

    // 'idle' with no override → use the original unmodified logo
    if (state === 'idle' && !overrideColor) return this.baseIcon;

    const { width, height } = this.baseIcon.getSize();
    const srcBitmap = this.baseIcon.toBitmap();
    const bitmap = Buffer.from(srcBitmap); // writable copy

    const color = overrideColor ?? STATE_COLORS[state];
    const dimFactor = state === 'disconnected' ? 0.65 : 1.0;
    const isModelsUnloaded = state === 'models-unloaded';

    for (let i = 0; i < bitmap.length; i += 4) {
      // BGRA byte order
      const b = bitmap[i];
      const g = bitmap[i + 1];
      const r = bitmap[i + 2];
      const a = bitmap[i + 3];

      if (a < 10) continue; // skip transparent

      const lum = 0.299 * r + 0.587 * g + 0.114 * b;

      if (isModelsUnloaded) {
        // Desaturate: grayscale + 30% original color, then dim to 70%
        const gray = lum;
        const blendR = Math.round((gray * 0.7 + r * 0.3) * 0.7);
        const blendG = Math.round((gray * 0.7 + g * 0.3) * 0.7);
        const blendB = Math.round((gray * 0.7 + b * 0.3) * 0.7);
        bitmap[i] = Math.min(blendB, 255);
        bitmap[i + 1] = Math.min(blendG, 255);
        bitmap[i + 2] = Math.min(blendR, 255);
      } else if (lum > MIC_LUMINANCE_THRESHOLD) {
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
        // null color (disconnected) → plain grayscale
        const gray = Math.round(Math.min(lum * dimFactor, 255));
        bitmap[i] = gray;
        bitmap[i + 1] = gray;
        bitmap[i + 2] = gray;
      }
    }

    // Draw black X overlay for error state
    if (state === 'error') {
      const xSize = Math.round(Math.min(width, height) * 0.6);
      const offsetX = Math.round((width - xSize) / 2);
      const offsetY = Math.round((height - xSize) / 2);
      const thickness = 2;

      for (let step = 0; step < xSize; step++) {
        for (let t = -thickness; t <= thickness; t++) {
          // Diagonal top-left → bottom-right
          const x1 = offsetX + step;
          const y1 = offsetY + step + t;
          if (x1 >= 0 && x1 < width && y1 >= 0 && y1 < height) {
            const idx = (y1 * width + x1) * 4;
            if (bitmap[idx + 3] > 10) {
              bitmap[idx] = 0; // B
              bitmap[idx + 1] = 0; // G
              bitmap[idx + 2] = 0; // R
            }
          }
          // Diagonal top-right → bottom-left
          const x2 = offsetX + xSize - 1 - step;
          const y2 = offsetY + step + t;
          if (x2 >= 0 && x2 < width && y2 >= 0 && y2 < height) {
            const idx = (y2 * width + x2) * 4;
            if (bitmap[idx + 3] > 10) {
              bitmap[idx] = 0; // B
              bitmap[idx + 1] = 0; // G
              bitmap[idx + 2] = 0; // R
            }
          }
        }
      }
    }

    return nativeImage.createFromBitmap(bitmap, { width, height });
  }

  // ─── Internal ───────────────────────────────────────────────────────────

  private applyState(): void {
    if (!this.tray) return;
    const icon = this.getIcon(this.state);
    this.tray.setImage(icon);

    // On Linux StatusNotifier, setImage alone may not trigger a visual refresh.
    // Setting the title forces a DBus property-change signal that nudges the
    // tray host to re-read the icon.
    const tooltip = STATE_TOOLTIP_MAP[this.state];
    if (process.platform === 'linux') {
      this.tray.setTitle(tooltip);
    }
    this.tray.setToolTip(tooltip);
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
      label: isMuted
        ? isRecording && !isLive
          ? 'Unmute Recording'
          : 'Unmute Live Mode'
        : isRecording && !isLive
          ? 'Mute Recording'
          : 'Mute Live Mode',
      enabled: isLive || isRecording,
      click: () => {
        if (isRecording && !isLive) {
          this.actions.toggleMute?.();
        } else {
          this.actions.toggleLiveMute?.();
        }
      },
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
        this.rebuildMenu();
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
