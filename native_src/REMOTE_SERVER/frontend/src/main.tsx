import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

// Detect basename from current URL path
// /notebook/* -> basename='/notebook', /record -> basename='/record', /admin -> basename='/admin'
const getBasename = (): string => {
  if (import.meta.env.DEV) return '/';
  const path = window.location.pathname;
  if (path.startsWith('/notebook')) return '/notebook';
  if (path.startsWith('/record')) return '/record';
  if (path.startsWith('/admin')) return '/admin';
  return '/';
};

const basename = getBasename();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
