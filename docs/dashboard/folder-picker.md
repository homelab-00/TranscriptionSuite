# Folder Picker (FR14)

The Audio Notebook QoL pack uses the **OS-native folder selection dialog**
for any "Destination folder" field — no free-text path input. Story 1.4
(Issue #104) ships the foundational primitive consumed by the empty-profile
screen (Story 1.5) and the profile-edit form.

## Architecture

```
React component
   │
   ▼
useFolderPicker() ──► window.electronAPI.fileIO.selectFolder()
   │                          │
   │                          ▼
   │               (preload contextBridge)
   │                          │
   │                          ▼
   │                ipcRenderer.invoke('dialog:selectFolder')
   │                          │
   │                          ▼
   │                ipcMain.handle('dialog:selectFolder')
   │                          │
   │                          ▼
   │                dialog.showOpenDialog(window, {
   │                  properties: ['openDirectory'],
   │                })
   ▼
chosen path (string) or null on cancel
```

The IPC handler already existed before Story 1.4; this story adds the
React-side hook + accessibility conventions for callers.

## Usage

```tsx
import { useFolderPicker } from '@/hooks/useFolderPicker';

function DestinationField() {
  const pickFolder = useFolderPicker();
  const [folder, setFolder] = useState<string>('');

  return (
    <div>
      <label htmlFor="dest">Destination folder</label>
      <input
        id="dest"
        type="text"
        readOnly
        value={folder}
        aria-label="Destination folder (read-only — use the Choose button)"
      />
      <button
        type="button"
        onClick={async () => {
          const chosen = await pickFolder();
          if (chosen !== null) setFolder(chosen);
        }}
        aria-label="Choose destination folder"
      >
        Choose folder…
      </button>
    </div>
  );
}
```

### Accessibility checklist (FR51, FR53)

- The button MUST have an `aria-label` like `"Choose destination folder"`
  (not bare `"Choose folder"`) so screen-reader users know which field
  the action targets.
- Tab order: Tabs into the button reach it after the read-only input.
- Activation: Both Enter and Space open the dialog (default `<button>`
  behaviour, no extra wiring needed).
- After dialog dismissal (cancel or accept), focus returns to the
  triggering button — Electron handles this automatically, no extra
  React state is required.

## Cross-platform notes

| Platform | Status | Notes |
|---|---|---|
| Linux KDE Wayland (primary target) | ✅ Tested | Native KDE dialog appears; XDG Portal handles the picker. |
| Windows 11 | ✅ Should work | Uses native Common Item Dialog (`IFileOpenDialog`) via Electron. |
| macOS | ✅ Should work | Uses NSOpenPanel; `properties: ['openDirectory']` selects folder mode. |

Linux KDE Wayland is the primary development target; Windows 11 + macOS
are exercised manually before each release. If you find a platform-specific
regression, document it inline here and file an issue.

## Web preview / Vitest

When `window.electronAPI` is not present (Vitest jsdom or a web preview
build), `useFolderPicker()` returns `null` from its callback — the caller
can branch on that and fall back to a free-text input or a "this feature
requires the desktop app" notice. Tests should mock `window.electronAPI`
when they need a non-null path.
