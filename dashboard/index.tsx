import React from 'react';
import ReactDOM from 'react-dom/client';
import './src/index.css';
import App from './App';
import { applyBlurEffectsBoot } from './src/utils/blurEffectsBoot';

// Issue #87 — Apply the persisted Blur effects preference synchronously
// before the first React render, so users who have disabled blur do not
// see a flash-of-blur on cold start. See blurEffectsBoot.ts for full
// rationale and edge-case handling.
applyBlurEffectsBoot();

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
