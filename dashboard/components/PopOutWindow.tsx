import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface PopOutWindowProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  width?: number;
  height?: number;
  children: ReactNode;
}

/**
 * Renders children into a separate native window using React Portal + window.open().
 * In Electron, setWindowOpenHandler intercepts the call and creates a real BrowserWindow.
 * Children remain in the parent React tree — all state, context, and hooks are shared.
 */
export function PopOutWindow({
  isOpen,
  onClose,
  title = 'Transcription Suite',
  width = 520,
  height = 600,
  children,
}: PopOutWindowProps) {
  const [containerEl] = useState(() => document.createElement('div'));
  const externalWindowRef = useRef<Window | null>(null);

  const closeHandler = useCallback(() => {
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;

    const externalWindow = window.open('', '', `width=${width},height=${height}`);

    if (!externalWindow) {
      console.error('PopOutWindow: window.open() returned null');
      onClose();
      return;
    }

    externalWindowRef.current = externalWindow;
    externalWindow.document.title = title;

    // Copy all stylesheets from parent so Tailwind classes work
    copyStyles(document, externalWindow.document);

    // Set up the body
    containerEl.style.height = '100%';
    externalWindow.document.body.appendChild(containerEl);
    externalWindow.document.body.style.margin = '0';
    externalWindow.document.body.style.backgroundColor = '#0f172a';
    externalWindow.document.body.style.color = '#e2e8f0';
    externalWindow.document.body.style.height = '100vh';
    externalWindow.document.body.style.overflow = 'hidden';

    // Watch for dynamically added/removed styles (Vite HMR in dev)
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node instanceof HTMLStyleElement) {
            const clone = externalWindow.document.createElement('style');
            clone.textContent = node.textContent;
            clone.dataset.sourceId = node.dataset.viteDevId ?? '';
            externalWindow.document.head.appendChild(clone);
          }
          if (node instanceof HTMLLinkElement && node.rel === 'stylesheet') {
            const clone = externalWindow.document.createElement('link');
            clone.rel = 'stylesheet';
            clone.href = node.href;
            externalWindow.document.head.appendChild(clone);
          }
        });
        mutation.removedNodes.forEach((node) => {
          if (node instanceof HTMLStyleElement && node.dataset.viteDevId) {
            const match = externalWindow.document.querySelector(
              `style[data-source-id="${node.dataset.viteDevId}"]`,
            );
            match?.remove();
          }
        });
      }
    });
    observer.observe(document.head, { childList: true });

    externalWindow.addEventListener('beforeunload', closeHandler);

    return () => {
      observer.disconnect();
      externalWindow.removeEventListener('beforeunload', closeHandler);
      externalWindow.close();
      externalWindowRef.current = null;
    };
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  // Update title reactively
  useEffect(() => {
    if (externalWindowRef.current) {
      externalWindowRef.current.document.title = title;
    }
  }, [title]);

  if (!isOpen) return null;

  return createPortal(children, containerEl);
}

function copyStyles(sourceDoc: Document, targetDoc: Document) {
  const links = sourceDoc.querySelectorAll('link[rel="stylesheet"]');
  links.forEach((link) => {
    const newLink = targetDoc.createElement('link');
    newLink.rel = 'stylesheet';
    newLink.href = (link as HTMLLinkElement).href;
    targetDoc.head.appendChild(newLink);
  });

  const styles = sourceDoc.querySelectorAll('style');
  styles.forEach((style) => {
    const newStyle = targetDoc.createElement('style');
    newStyle.textContent = style.textContent;
    targetDoc.head.appendChild(newStyle);
  });
}
