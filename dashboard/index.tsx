import React from 'react';
import ReactDOM from 'react-dom/client';
import './src/index.css';
import App from './App';
import { migrateLegacyAppearanceConfig } from './src/utils/migrateLegacyAppearanceConfig';
import { applyBlurEffectsBoot } from './src/utils/blurEffectsBoot';
import { applyIdleAnimationsBoot } from './src/utils/idleAnimationsBoot';
import { installIdleVisibilityGate } from './src/utils/idleVisibilityGate';

// GH-87 — Migrate any legacy combined "Low idle usage" choice to the two
// independent blur/idle keys BEFORE the boot probes read them, so the very
// first painted frame after upgrade reflects the migrated state. See
// migrateLegacyAppearanceConfig.ts.
migrateLegacyAppearanceConfig();

// Issue #87 — Apply the persisted Blur effects preference synchronously
// before the first React render, so users who have disabled blur do not
// see a flash-of-blur on cold start. See blurEffectsBoot.ts for full
// rationale and edge-case handling.
applyBlurEffectsBoot();

// GH-87 — Apply the persisted Idle animations preference synchronously
// before first render (same pre-paint rationale as blur), and install the
// always-on visibility gate that pauses idle waves while the window is
// hidden. See idleAnimationsBoot.ts and idleVisibilityGate.ts.
applyIdleAnimationsBoot();
installIdleVisibilityGate();

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Could not find root element to mount to');
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
