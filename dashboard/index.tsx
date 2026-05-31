import React from 'react';
import ReactDOM from 'react-dom/client';
import './src/index.css';
import App from './App';
import { applyBlurEffectsBoot } from './src/utils/blurEffectsBoot';
import { applyLowIdleUsageBoot } from './src/utils/lowIdleUsageBoot';
import { installIdleVisibilityGate } from './src/utils/idleVisibilityGate';

// Issue #87 — Apply the persisted Blur effects preference synchronously
// before the first React render, so users who have disabled blur do not
// see a flash-of-blur on cold start. See blurEffectsBoot.ts for full
// rationale and edge-case handling.
applyBlurEffectsBoot();

// GH-124 Part C / issue 87 — Apply the persisted Low idle usage preference
// synchronously before first render (same pre-paint rationale as blur), and
// install the always-on visibility gate that pauses idle waves while the
// window is hidden. See lowIdleUsageBoot.ts and idleVisibilityGate.ts.
applyLowIdleUsageBoot();
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
