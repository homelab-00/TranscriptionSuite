# TranscriptionSuite Landing Page — Design Spec

**Date:** 2026-04-03
**Status:** Approved
**Repo:** `/home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage`
**Hosted on:** Cloudflare Pages (site) + Cloudflare R2 (video assets)

---

## 1. Overview

A single-page static landing page for TranscriptionSuite that showcases the app's features with automated screenshots and video recordings, tells the project's origin story, and points to GitHub. The page visually mirrors the Electron dashboard's frosted-glass design language.

## 2. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | Astro (static output mode) | Component-based, ships zero client JS by default |
| Styling | Tailwind CSS v4 with `@theme` tokens copied from the app | Exact visual parity with the dashboard |
| Hosting | Cloudflare Pages | Free tier, auto-deploy from GitHub on push to `main` |
| Video storage | Cloudflare R2 (public bucket) | Free tier (10GB/10M reads), keeps large videos out of git |
| Language | TypeScript / Astro components | Type safety, familiar from the dashboard codebase |

**No SSR.** The Astro config uses static output mode — pure HTML/CSS/JS at build time.

## 3. Project Structure

```
TranscriptionSuite_Webpage/
├── src/
│   ├── layouts/
│   │   └── BaseLayout.astro          # <html> shell, meta, fonts, global CSS
│   ├── components/
│   │   ├── Navbar.astro              # Sticky frosted-glass nav
│   │   ├── Hero.astro                # Headline, subtitle, CTAs, hero screenshot
│   │   ├── FeatureCard.astro         # Single glass card (icon + title + desc + screenshot)
│   │   ├── FeatureGrid.astro         # 3x3 grid container, passes data to FeatureCard
│   │   ├── VideoCard.astro           # Video player card (thumbnail + play overlay)
│   │   ├── VideoSection.astro        # 2-column video grid
│   │   ├── AboutSection.astro        # Origin story in a glass card
│   │   ├── GitHubCTA.astro           # Full-width CTA section
│   │   └── Footer.astro              # Minimal footer
│   ├── styles/
│   │   └── global.css                # @theme tokens, glass utilities, gradients, animations
│   ├── assets/
│   │   ├── screenshots/              # Playwright-generated PNGs (committed to repo)
│   │   ├── videos/                   # Local staging only; videos deploy to R2
│   │   └── logo/                     # Logo assets copied from app repo
│   └── pages/
│       └── index.astro               # Composes all sections into the landing page
├── public/
│   └── favicon.ico
├── astro.config.mjs
├── package.json
└── tsconfig.json
```

**Repo location:** `/home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage`
This is a separate git repository, fully independent from the app repo.

## 4. Page Sections (top to bottom)

### 4.1 Navbar

- **Position:** Sticky, top of viewport, z-50
- **Background:** `glass-surface` (`rgba(0,0,0,0.4)`) + `backdrop-blur-md` (12px)
- **Border:** Bottom `1px solid rgba(255,255,255,0.1)`
- **Left:** Logo icon + "TranscriptionSuite" text
- **Right:** Section anchor links (Features, Videos, About) + GitHub icon link (cyan accent)
- **Behavior:** Smooth-scroll to anchored sections on click

### 4.2 Hero

- **Sub-heading:** "100% Local · 100% Private" — uppercase, `tracking-widest`, cyan accent
- **Headline:** "Speech-to-Text, Your Way" — `text-4xl` / `font-bold`, "Your Way" in gradient text (cyan → magenta)
- **Subtitle:** One-sentence app description — `text-sm` / `text-slate-300`, max-width constrained
- **CTAs:** Two buttons side by side:
  - Primary: "View on GitHub" — cyan background, dark text
  - Secondary: "Watch Tour ▶" — glass border, white text (scrolls to Videos section)
- **Hero screenshot:** Below the CTAs. A Playwright-captured Session view screenshot, wrapped in window-chrome frame (three colored dots + title bar). Subtle floating CSS animation.

### 4.3 Feature Grid

- **Section label:** "Features" — uppercase, magenta accent
- **Section heading:** "Everything You Need" — `text-2xl` / `font-semibold`
- **Grid:** 3 columns × 3 rows, gap-4
- **Each card** (`FeatureCard.astro`):
  - Glass background (`glass-100` + border)
  - Screenshot thumbnail area at top (Playwright-captured, rounded top corners, ~120px tall, `object-cover`)
  - Icon (emoji or SVG) + feature title inline — `text-sm` / `font-semibold`
  - One-liner description — `text-xs` / `text-slate-400`
  - Hover: subtle border brightening or glow
- **Responsive:** Collapses to 2-col on tablet, 1-col on mobile
- **Scroll animation:** Cards stagger-fade-in (CSS `animation-delay` per card, triggered by IntersectionObserver)

**The 9 features:**

| # | Feature | Icon | One-liner |
|---|---------|------|-----------|
| 1 | 100% Local & Private | Lock | Your audio never leaves your machine |
| 2 | Longform Transcription | Document | Hours of audio transcribed in seconds |
| 3 | Live Mode | Lightning | Real-time sentence-by-sentence transcription |
| 4 | Audio Notebook | Notebook | Calendar view, full-text search, playback |
| 5 | Speaker Diarization | People | Identify who said what |
| 6 | Multi-Backend STT | Brain/Gear | Whisper, NeMo, VibeVoice, whisper.cpp |
| 7 | Remote Access | Globe | Access from anywhere via Tailscale or LAN |
| 8 | Cross-Platform | Monitor | Linux, Windows, macOS (Apple Silicon) |
| 9 | LM Studio Integration | Robot/AI | Chat with AI about your transcription notes |

### 4.4 Videos

- **Section label:** "See It In Action" — uppercase, orange accent
- **Section heading:** "Tour & How-To" — `text-2xl` / `font-semibold`
- **Grid:** 2 columns
- **Each card** (`VideoCard.astro`):
  - Glass background with rounded corners
  - Video thumbnail area with play button overlay (centered circle, ▶ icon)
  - On click: plays the video inline (HTML5 `<video>` with controls)
  - Title + short description below the thumbnail
- **Video sources:** Loaded from R2 public URLs
- **Responsive:** Stacks to 1-col on mobile

**The 2 videos:**

| Video | Content | Duration |
|-------|---------|----------|
| App Tour | Walks through Session → record → Notebook → note → Server Config | ~60-90s |
| Quick Start | Server tab → start container → Session → record → result | ~30-45s |

### 4.5 About

- **Section label:** "The Story" — uppercase, cyan accent
- **Section heading:** "About This Project" — `text-2xl` / `font-semibold`
- **Content:** Lightly edited version of README section 9.1, inside a glass card. Preserves the authentic voice — vibecoding disclosure, mech-eng background, learning journey, dogfooding commitment, credit to RealtimeSTT.
- **Tone adjustments from raw README:** Remove markdown-isms, add brief context sentence for visitors who scrolled directly here, keep it concise (one short paragraph).

### 4.6 GitHub CTA

- **Background:** Subtle gradient wash (transparent → faint cyan tint at bottom)
- **Headline:** "Open Source & Free" — `text-2xl` / `font-bold`
- **Subtitle:** "Star the repo, report bugs, or contribute" — `text-sm` / `text-slate-400`
- **Button:** "⭐ View on GitHub" — cyan background, dark text, links to `https://github.com/homelab-00/TranscriptionSuite`

### 4.7 Footer

- **Border:** Top `1px solid rgba(255,255,255,0.05)`
- **Left:** "© 2026 homelab-00"
- **Right:** "Built with Astro · Hosted on Cloudflare"
- **Font:** `text-xs` / `text-slate-600`

## 5. Visual Design

### 5.1 Background

The same triple radial gradient as the app's `body`:

```css
background-color: #0f172a;
background-image:
  radial-gradient(at 0% 0%, hsla(253,16%,7%,1) 0, transparent 50%),
  radial-gradient(at 50% 0%, hsla(225,39%,30%,1) 0, transparent 50%),
  radial-gradient(at 100% 0%, hsla(339,49%,30%,1) 0, transparent 50%);
```

Since this is a scrollable page (unlike the app which is `overflow: hidden`), the gradient is applied with `background-attachment: fixed` so it stays in place as the user scrolls.

### 5.2 Glass Surfaces

Copied from the app's `@theme`:

| Token | Value | Used by |
|-------|-------|---------|
| `glass-100` | `rgba(0,0,0,0.3)` | Feature cards, video cards, about card |
| `glass-200` | `rgba(0,0,0,0.5)` | — |
| `glass-300` | `rgba(0,0,0,0.7)` | — |
| `glass-border` | `rgba(255,255,255,0.1)` | All card borders, nav border |
| `glass-surface` | `rgba(0,0,0,0.4)` | Navbar background |

### 5.3 Accent Colors

| Color | Hex | Role on landing page |
|-------|-----|---------------------|
| Cyan | `#22d3ee` | Primary CTAs, GitHub button, nav highlight, "About" section accent, selection color |
| Magenta | `#d946ef` | Hero gradient text, "Features" section accent |
| Orange | `#fb923c` | "Videos" section accent |

### 5.4 Typography

- **Font family:** Inter, sans-serif (loaded via Google Fonts or self-hosted)
- **Selection:** `::selection { background: #22d3ee; color: #0f172a; }`

### 5.5 sRGB Enforcement

All colors are sRGB hex or `rgba()`. No `oklch()`, `oklab()`, or `color-mix(in oklab, ...)`. Since the landing page uses Tailwind v4 with explicit `@theme` hex overrides (copied from the app), this is enforced by the same mechanism.

### 5.6 Screenshot Framing

Each Playwright screenshot is displayed inside a CSS "window chrome" frame:

- **Title bar:** Dark background (`rgba(0,0,0,0.4)`), three colored dots (red `#ef4444`, amber `#fbbf24`, green `#22c55e`), window title text in `text-slate-500`
- **Border:** `glass-border` with `rounded-xl`
- **This is pure CSS** — no image compositing needed

## 6. Scroll Animations

All animations are CSS-based, triggered by a single IntersectionObserver script (Astro `<script>` tag, not a framework island).

| Element | Animation | Trigger |
|---------|-----------|---------|
| Each page section | Fade in + translate-y 20px → 0 | Section enters viewport (threshold 0.1) |
| Feature cards | Same fade-in, staggered by `animation-delay` (50ms increments) | Grid enters viewport |
| Hero screenshot | Subtle floating (`translateY` oscillation, 3s ease-in-out infinite) | Always active |
| Video play button | Scale pulse on hover | CSS `:hover` |

**No scroll-linked animations** (`animation-timeline: scroll()`) — browser support is still incomplete. Stick to IntersectionObserver for enter animations.

## 7. Playwright Automation (App Repo)

Scripts live in the **app repo** at `TranscriptionSuite/scripts/webpage-assets/`.

### 7.1 Screenshot Capture (`capture-screenshots.ts`)

- Uses `@playwright/test`'s `electron.launch()` to start the dashboard
- Requires: the Docker backend container running, a display server (or `xvfb-run`)
- Navigates to each view, waits for network idle + 500ms settle
- Captures 9 screenshots (the "100% Local" card reuses `hero.png`):
  - `hero.png` — Session view, default state (also used for the "100% Local" feature card)
  - `feature-longform.png` — Session view with a completed transcription visible
  - `feature-live.png` — Session view with Live Mode active
  - `feature-notebook.png` — Notebook calendar view
  - `feature-diarization.png` — Audio Note modal showing speaker-labeled transcript
  - `feature-multibackend.png` — Server Config showing backend/model options
  - `feature-remote.png` — Server Config or Settings showing remote connection
  - `feature-crossplatform.png` — Server Config showing setup status
  - `feature-lmstudio.png` — Notebook view with LM Studio chat panel
- Output directory: configurable via CLI arg, defaults to `../../TypeScript_Projects/TranscriptionSuite_Webpage/src/assets/screenshots/`

### 7.2 Video Recording (`record-videos.ts`)

- Same Electron launch approach
- Uses Playwright's `browserContext.newPage()` with `recordVideo` option
- Records two sessions:
  - **tour.webm** — Navigates: Session → triggers a short recording → Notebook → opens a note → Server Config. Includes mouse movement for visual guidance. Target: 60-90 seconds.
  - **quickstart.webm** — Navigates: Server tab → container start → Session → record → transcription result. Target: 30-45 seconds.
- Output: `.webm` files to a staging directory
- Post-processing: none initially (Playwright's raw recording). Can add ffmpeg conversion to `.mp4` later if browser compatibility requires it.

### 7.3 Asset Sync Script (`sync-assets.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

WEBPAGE_REPO="${1:-../../TypeScript_Projects/TranscriptionSuite_Webpage}"
R2_BUCKET="transcriptionsuite-assets"

echo "=== Capturing screenshots ==="
npx playwright test scripts/webpage-assets/capture-screenshots.ts

echo "=== Recording videos ==="
npx playwright test scripts/webpage-assets/record-videos.ts

echo "=== Uploading videos to R2 ==="
for f in scripts/webpage-assets/output/videos/*.webm; do
  wrangler r2 object put "${R2_BUCKET}/videos/$(basename "$f")" --file "$f"
done

echo "=== Done ==="
echo "Screenshots → ${WEBPAGE_REPO}/src/assets/screenshots/"
echo "Videos → R2 bucket '${R2_BUCKET}'"
```

**When to run:** Manually, after UI changes or new features. Not automated in CI.

**Prerequisites:**
- Docker backend running (for real app data)
- Display server or `xvfb-run` on headless Linux
- `wrangler` CLI authenticated with Cloudflare

## 8. Cloudflare Deployment

### 8.1 Pages Configuration

- **Repository:** `homelab-00/TranscriptionSuite_Webpage` (GitHub)
- **Build command:** `npm run build`
- **Output directory:** `dist/`
- **Auto-deploy:** On push to `main`

### 8.2 R2 Bucket

- **Bucket name:** `transcriptionsuite-assets`
- **Public access:** Enabled (or mapped to a subdomain like `assets.yourdomain.com`)
- **Contents:** Video files only (`tour.webm`, `quickstart.webm`)

### 8.3 Custom Domain

- Add purchased domain in Cloudflare Pages settings
- DNS configured automatically (domain already on Cloudflare)

### 8.4 Free Tier Limits

| Resource | Limit | Expected usage |
|----------|-------|----------------|
| Pages builds | 500/month | ~10/month |
| Pages bandwidth | Unlimited (static) | Minimal |
| R2 storage | 10 GB | <100 MB (2 videos) |
| R2 reads | 10M/month | Negligible |

## 9. Responsive Behavior

| Breakpoint | Feature grid | Video grid | Nav |
|------------|-------------|------------|-----|
| Desktop (≥1024px) | 3 columns | 2 columns | Horizontal links |
| Tablet (≥640px) | 2 columns | 2 columns | Horizontal links (smaller) |
| Mobile (<640px) | 1 column | 1 column | Hamburger menu |

## 10. Out of Scope

- No analytics, cookie banners, or tracking
- No blog, changelog, or docs section (GitHub README covers these)
- No email signup or mailing list
- No dark/light mode toggle (always dark, matching the app)
- No i18n (English only)
- No CI for Playwright asset generation (manual only)
