/**
 * GH-124 Part C / issue 87 — Always-on idle-animation visibility gate.
 *
 * Registers a single `visibilitychange` listener that toggles
 * `data-doc-hidden="true"` on the document element whenever the window is
 * hidden (minimized or backgrounded). A CSS rule pauses the idle
 * AudioVisualizer waves while that attribute is present, so no compositor
 * work happens for an unseen window.
 *
 * This is a correctness/hygiene fix independent of the Low idle usage
 * toggle — it fires only on minimize/background, not the reporter "app
 * visible" idle case. There is no per-frame JavaScript: a single listener
 * flips one CSS attribute.
 */

let installed = false;

export function installIdleVisibilityGate(): void {
  if (installed) return;
  if (typeof document === 'undefined') return;
  installed = true;

  const sync = (): void => {
    if (document.visibilityState === 'hidden') {
      document.documentElement.dataset.docHidden = 'true';
    } else {
      delete document.documentElement.dataset.docHidden;
    }
  };

  document.addEventListener('visibilitychange', sync);
  // Apply the current state immediately in case the window starts hidden.
  sync();
}
