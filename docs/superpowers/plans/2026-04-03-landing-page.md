# TranscriptionSuite Landing Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a static landing page that mirrors the Electron dashboard's frosted-glass design, showcasing features with automated screenshots/videos, and deployed to Cloudflare Pages.

**Architecture:** Astro static site with Tailwind v4, using the same `@theme` tokens as the dashboard app. The landing page lives in its own git repo (`TranscriptionSuite_Webpage`). Playwright scripts in the app repo generate screenshots and video recordings of the running Electron app, which are then used as static assets on the landing page. Videos are served from Cloudflare R2.

**Tech Stack:** Astro 5.x, Tailwind CSS v4, TypeScript, Playwright (for asset automation in the app repo), Cloudflare Pages + R2

**Design Spec:** `docs/superpowers/specs/2026-04-03-landing-page-design.md` (in app repo)

**Two repos involved:**
- **Webpage repo** (Tasks 1-10): `/home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage`
- **App repo** (Tasks 11-13): `/home/Bill/Code_Projects/Python_Projects/TranscriptionSuite`

---

## Task 1: Scaffold Astro Project

**Files:**
- Create: `/home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage/` (entire project)
- Create: `astro.config.mjs`
- Create: `src/styles/global.css`
- Create: `tsconfig.json`
- Create: `.gitignore`

- [ ] **Step 1: Create parent directory and init Astro project**

```bash
mkdir -p /home/Bill/Code_Projects/TypeScript_Projects
cd /home/Bill/Code_Projects/TypeScript_Projects
npm create astro@latest TranscriptionSuite_Webpage -- --template minimal --no-install --typescript strict
```

Expected: A `TranscriptionSuite_Webpage/` directory with minimal Astro scaffold.

- [ ] **Step 2: Install dependencies**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
npm install
npx astro add tailwind -- --yes
```

Expected: `@tailwindcss/vite` added to `astro.config.mjs` automatically. Tailwind v4 installed.

- [ ] **Step 3: Verify astro.config.mjs has Tailwind plugin and static output**

Read `astro.config.mjs`. It should have the `@tailwindcss/vite` plugin. Update it to explicitly set `output: 'static'` and the site URL:

```js
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  output: 'static',
  site: 'https://transcriptionsuite.com',
  vite: {
    plugins: [tailwindcss()],
  },
});
```

Note: Replace `transcriptionsuite.com` with the actual purchased domain.

- [ ] **Step 4: Write global.css with app design tokens**

Create `src/styles/global.css` with the `@theme` block copied from the dashboard app's `dashboard/src/index.css`, plus landing-page-specific styles:

```css
@import 'tailwindcss';

/* --- Tailwind Theme Extension (copied from TranscriptionSuite dashboard) --- */
@theme {
  --font-sans: 'Inter', sans-serif;

  /* Glass colors */
  --color-glass-100: rgba(0, 0, 0, 0.3);
  --color-glass-200: rgba(0, 0, 0, 0.5);
  --color-glass-300: rgba(0, 0, 0, 0.7);
  --color-glass-border: rgba(255, 255, 255, 0.1);
  --color-glass-surface: rgba(0, 0, 0, 0.4);

  /* Accent colors */
  --color-accent-cyan: #22d3ee;
  --color-accent-magenta: #d946ef;
  --color-accent-orange: #fb923c;
  --color-accent-rose: #f43f5e;

  /* Backdrop blur */
  --backdrop-blur-xs: 2px;

  /*
   * Tailwind v3 sRGB palette overrides.
   * Pin every referenced shade back to the exact v3 hex value so the
   * rendered output matches the dashboard app (which uses v3 CDN values).
   */

  /* slate */
  --color-slate-200: #e2e8f0;
  --color-slate-300: #cbd5e1;
  --color-slate-400: #94a3b8;
  --color-slate-500: #64748b;
  --color-slate-600: #475569;
  --color-slate-700: #334155;
  --color-slate-800: #1e293b;
  --color-slate-900: #0f172a;

  /* green */
  --color-green-300: #86efac;
  --color-green-400: #4ade80;
  --color-green-500: #22c55e;

  /* red */
  --color-red-400: #f87171;
  --color-red-500: #ef4444;

  /* amber */
  --color-amber-400: #fbbf24;

  /* black / white */
  --color-black: #000000;
  --color-white: #ffffff;
}

/* --- Global Styles --- */
html {
  scroll-behavior: smooth;
  /* Offset anchor scroll targets below the sticky navbar (h-16 = 64px) */
  scroll-padding-top: 5rem;
}

body {
  background-color: #0f172a;
  background-image:
    radial-gradient(at 0% 0%, hsla(253, 16%, 7%, 1) 0, transparent 50%),
    radial-gradient(at 50% 0%, hsla(225, 39%, 30%, 1) 0, transparent 50%),
    radial-gradient(at 100% 0%, hsla(339, 49%, 30%, 1) 0, transparent 50%);
  background-attachment: fixed;
  color: white;
}

/* Global Selection Styling */
::selection {
  background-color: #22d3ee;
  color: #0f172a;
}

::-moz-selection {
  background-color: #22d3ee;
  color: #0f172a;
}

/* Tailwind v4 maps bg-gradient-* to oklab interpolation; force sRGB. */
.bg-gradient-to-b {
  --tw-gradient-position: to bottom;
  background-image: linear-gradient(var(--tw-gradient-stops));
}

/* Custom Scrollbar */
::-webkit-scrollbar {
  width: 8px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background-color: rgba(255, 255, 255, 0.2);
  border-radius: 9999px;
}
::-webkit-scrollbar-thumb:hover {
  background-color: rgba(255, 255, 255, 0.4);
}

/* --- Scroll Animations --- */
@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-fade-in-up {
  opacity: 0;
}

.animate-fade-in-up.is-visible {
  animation: fade-in-up 0.6s ease-out forwards;
}

/* Hero screenshot float */
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.animate-float {
  animation: float 3s ease-in-out infinite;
}
```

- [ ] **Step 5: Create asset directories and copy logo**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
mkdir -p src/assets/screenshots src/assets/videos src/assets/logo
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/logo.png src/assets/logo/
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/logo.svg src/assets/logo/
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/logo_wide.png src/assets/logo/
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/logo.ico public/favicon.ico
```

Also copy the existing screenshots as initial placeholders until Playwright automation is built:

```bash
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-1.png src/assets/screenshots/hero.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-1.png src/assets/screenshots/feature-longform.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-1.png src/assets/screenshots/feature-live.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-2.png src/assets/screenshots/feature-notebook.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-3.png src/assets/screenshots/feature-diarization.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-4.png src/assets/screenshots/feature-multibackend.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-4.png src/assets/screenshots/feature-remote.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-4.png src/assets/screenshots/feature-crossplatform.png
cp /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/docs/assets/shot-2.png src/assets/screenshots/feature-lmstudio.png
```

- [ ] **Step 6: Update .gitignore**

Append to the existing `.gitignore`:

```
# Video staging (videos deploy to R2, not git)
src/assets/videos/

# Astro
dist/
.astro/
```

- [ ] **Step 7: Verify build works**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
npm run build
```

Expected: Successful build with output in `dist/`.

- [ ] **Step 8: Init git repo and commit**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
git init
git add .
git commit -m "chore: scaffold Astro project with Tailwind v4 and app design tokens"
```

---

## Task 2: BaseLayout Component

**Files:**
- Create: `src/layouts/BaseLayout.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create BaseLayout.astro**

Create `src/layouts/BaseLayout.astro`:

```astro
---
interface Props {
  title: string;
  description: string;
}

const { title, description } = Astro.props;
---

<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content={description} />
    <link rel="icon" type="image/x-icon" href="/favicon.ico" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
      rel="stylesheet"
    />
    <title>{title}</title>
  </head>
  <body class="min-h-screen antialiased">
    <slot />

    <script>
      // IntersectionObserver for scroll animations
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-visible');
              observer.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.1 }
      );

      document.querySelectorAll('.animate-fade-in-up').forEach((el) => {
        observer.observe(el);
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Update index.astro to use BaseLayout**

Replace the contents of `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <main>
    <p class="text-white text-center py-20">Landing page coming soon...</p>
  </main>
</BaseLayout>
```

- [ ] **Step 3: Verify build and dev server**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
npm run dev
```

Open the dev URL in a browser. Verify: dark background with triple radial gradient, white centered text, Inter font, custom scrollbar, cyan selection color.

- [ ] **Step 4: Commit**

```bash
git add src/layouts/BaseLayout.astro src/pages/index.astro
git commit -m "feat: add BaseLayout with meta tags, fonts, and scroll animations"
```

---

## Task 3: Navbar Component

**Files:**
- Create: `src/components/Navbar.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create Navbar.astro**

Create `src/components/Navbar.astro`:

```astro
---
import { Image } from 'astro:assets';
import logo from '../assets/logo/logo.png';

const navLinks = [
  { label: 'Features', href: '#features' },
  { label: 'Videos', href: '#videos' },
  { label: 'About', href: '#about' },
];

const githubUrl = 'https://github.com/homelab-00/TranscriptionSuite';
---

<nav
  class="sticky top-0 z-50 border-b border-glass-border bg-glass-surface backdrop-blur-md"
>
  <div class="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
    <!-- Logo + Name -->
    <a href="#" class="flex items-center gap-2">
      <Image src={logo} alt="TranscriptionSuite logo" width={28} height={28} class="rounded-md" />
      <span class="text-sm font-semibold text-white">TranscriptionSuite</span>
    </a>

    <!-- Desktop Links -->
    <div class="hidden items-center gap-6 sm:flex">
      {navLinks.map((link) => (
        <a
          href={link.href}
          class="text-sm text-slate-400 transition-colors hover:text-white"
        >
          {link.label}
        </a>
      ))}
      <a
        href={githubUrl}
        target="_blank"
        rel="noopener noreferrer"
        class="text-sm font-medium text-accent-cyan transition-colors hover:text-cyan-300"
      >
        <!-- GitHub icon (inline SVG) -->
        <svg class="inline-block h-4 w-4 mr-1 -mt-0.5" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
        </svg>
        GitHub
      </a>
    </div>

    <!-- Mobile Hamburger -->
    <button
      id="mobile-menu-btn"
      class="sm:hidden text-slate-400 hover:text-white"
      aria-label="Toggle menu"
    >
      <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
      </svg>
    </button>
  </div>

  <!-- Mobile Menu (hidden by default) -->
  <div
    id="mobile-menu"
    class="hidden border-t border-glass-border bg-glass-surface px-6 py-4 backdrop-blur-md sm:hidden"
  >
    {navLinks.map((link) => (
      <a
        href={link.href}
        class="mobile-nav-link block py-2 text-sm text-slate-400 transition-colors hover:text-white"
      >
        {link.label}
      </a>
    ))}
    <a
      href={githubUrl}
      target="_blank"
      rel="noopener noreferrer"
      class="block py-2 text-sm font-medium text-accent-cyan"
    >
      GitHub
    </a>
  </div>
</nav>

<script>
  const btn = document.getElementById('mobile-menu-btn');
  const menu = document.getElementById('mobile-menu');
  btn?.addEventListener('click', () => {
    menu?.classList.toggle('hidden');
  });

  // Close mobile menu when a link is clicked
  document.querySelectorAll('.mobile-nav-link').forEach((link) => {
    link.addEventListener('click', () => {
      menu?.classList.add('hidden');
    });
  });
</script>
```

- [ ] **Step 2: Add Navbar to index.astro**

Update `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <p class="text-white text-center py-20">Sections coming soon...</p>
  </main>
</BaseLayout>
```

- [ ] **Step 3: Verify in dev server**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
npm run dev
```

Verify: Sticky glass navbar with logo, section links, GitHub link (cyan). Mobile: hamburger menu toggles link list. Click a link — smooth scroll (will work once sections have matching IDs).

- [ ] **Step 4: Commit**

```bash
git add src/components/Navbar.astro src/pages/index.astro
git commit -m "feat: add sticky frosted-glass navbar with mobile hamburger menu"
```

---

## Task 4: Hero Component

**Files:**
- Create: `src/components/Hero.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create Hero.astro**

Create `src/components/Hero.astro`:

```astro
---
import { Image } from 'astro:assets';
import heroScreenshot from '../assets/screenshots/hero.png';

const githubUrl = 'https://github.com/homelab-00/TranscriptionSuite';
---

<section class="px-6 pb-16 pt-20 md:pb-24 md:pt-28">
  <div class="mx-auto max-w-4xl text-center">
    <!-- Sub-heading -->
    <p class="mb-3 text-xs font-medium uppercase tracking-widest text-accent-cyan">
      100% Local &middot; 100% Private
    </p>

    <!-- Headline -->
    <h1 class="mb-4 text-4xl font-bold leading-tight text-white md:text-5xl">
      Speech-to-Text,<br />
      <span
        class="bg-gradient-to-r from-accent-cyan to-accent-magenta bg-clip-text text-transparent"
      >
        Your Way
      </span>
    </h1>

    <!-- Subtitle -->
    <p class="mx-auto mb-8 max-w-xl text-sm leading-relaxed text-slate-300 md:text-base">
      Longform &amp; live transcription, speaker diarization, audio notebook
      &mdash; powered by Whisper, NeMo, VibeVoice &amp; more.
      Runs entirely on your machine.
    </p>

    <!-- CTAs -->
    <div class="mb-12 flex items-center justify-center gap-3">
      <a
        href={githubUrl}
        target="_blank"
        rel="noopener noreferrer"
        class="rounded-lg bg-accent-cyan px-6 py-2.5 text-sm font-semibold text-slate-900 transition-opacity hover:opacity-90"
      >
        View on GitHub
      </a>
      <a
        href="#videos"
        class="rounded-lg border border-glass-border px-6 py-2.5 text-sm font-medium text-white transition-colors hover:border-slate-500"
      >
        Watch Tour &#9654;
      </a>
    </div>

    <!-- Hero Screenshot in window chrome -->
    <div class="animate-float mx-auto max-w-3xl">
      <div class="overflow-hidden rounded-xl border border-glass-border bg-glass-100">
        <!-- Title bar -->
        <div class="flex items-center gap-1.5 bg-black/40 px-3 py-2">
          <div class="h-2.5 w-2.5 rounded-full bg-red-500"></div>
          <div class="h-2.5 w-2.5 rounded-full bg-amber-400"></div>
          <div class="h-2.5 w-2.5 rounded-full bg-green-500"></div>
          <span class="ml-2 text-xs text-slate-500">TranscriptionSuite — Session</span>
        </div>
        <!-- Screenshot -->
        <Image
          src={heroScreenshot}
          alt="TranscriptionSuite Session view showing the main transcription interface"
          class="w-full"
        />
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Add Hero to index.astro**

Update `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import Hero from '../components/Hero.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <Hero />
  </main>
</BaseLayout>
```

- [ ] **Step 3: Verify in dev server**

Verify: Sub-heading in cyan uppercase, "Your Way" in cyan→magenta gradient, subtitle below, two CTA buttons, floating screenshot in window chrome frame. The screenshot floats gently up and down.

- [ ] **Step 4: Commit**

```bash
git add src/components/Hero.astro src/pages/index.astro
git commit -m "feat: add hero section with gradient headline, CTAs, and framed screenshot"
```

---

## Task 5: FeatureCard and FeatureGrid Components

**Files:**
- Create: `src/components/FeatureCard.astro`
- Create: `src/components/FeatureGrid.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create FeatureCard.astro**

Create `src/components/FeatureCard.astro`:

```astro
---
import { Image } from 'astro:assets';

interface Props {
  icon: string;
  title: string;
  description: string;
  screenshot: ImageMetadata;
  screenshotAlt: string;
  delay: number;
}

const { icon, title, description, screenshot, screenshotAlt, delay } = Astro.props;
---

<div
  class="animate-fade-in-up group overflow-hidden rounded-xl border border-glass-border bg-glass-100 transition-colors hover:border-slate-500"
  style={`animation-delay: ${delay}ms;`}
>
  <!-- Screenshot thumbnail -->
  <div class="h-28 overflow-hidden">
    <Image
      src={screenshot}
      alt={screenshotAlt}
      class="h-full w-full object-cover object-top transition-transform duration-300 group-hover:scale-105"
    />
  </div>
  <!-- Content -->
  <div class="p-4">
    <div class="mb-1 flex items-center gap-2">
      <span class="text-lg">{icon}</span>
      <h3 class="text-sm font-semibold text-white">{title}</h3>
    </div>
    <p class="text-xs leading-relaxed text-slate-400">{description}</p>
  </div>
</div>
```

- [ ] **Step 2: Create FeatureGrid.astro**

Create `src/components/FeatureGrid.astro`:

```astro
---
import FeatureCard from './FeatureCard.astro';

import heroImg from '../assets/screenshots/hero.png';
import longformImg from '../assets/screenshots/feature-longform.png';
import liveImg from '../assets/screenshots/feature-live.png';
import notebookImg from '../assets/screenshots/feature-notebook.png';
import diarizationImg from '../assets/screenshots/feature-diarization.png';
import multibackendImg from '../assets/screenshots/feature-multibackend.png';
import remoteImg from '../assets/screenshots/feature-remote.png';
import crossplatformImg from '../assets/screenshots/feature-crossplatform.png';
import lmstudioImg from '../assets/screenshots/feature-lmstudio.png';

const features = [
  {
    icon: '\u{1F512}',
    title: '100% Local & Private',
    description: 'Your audio never leaves your machine. No cloud, no telemetry, no compromises.',
    screenshot: heroImg,
    screenshotAlt: 'Session view showing fully local transcription',
  },
  {
    icon: '\u{1F4DD}',
    title: 'Longform Transcription',
    description: 'Hours of audio transcribed in seconds with NVIDIA GPU acceleration.',
    screenshot: longformImg,
    screenshotAlt: 'Session view with a completed transcription result',
  },
  {
    icon: '\u26A1',
    title: 'Live Mode',
    description: 'Real-time sentence-by-sentence transcription for continuous dictation.',
    screenshot: liveImg,
    screenshotAlt: 'Session view with Live Mode active',
  },
  {
    icon: '\u{1F4D3}',
    title: 'Audio Notebook',
    description: 'Calendar-based view, full-text search, and audio playback for all your notes.',
    screenshot: notebookImg,
    screenshotAlt: 'Audio Notebook with calendar view',
  },
  {
    icon: '\u{1F465}',
    title: 'Speaker Diarization',
    description: 'Identify who said what with automatic speaker labeling and subtitling.',
    screenshot: diarizationImg,
    screenshotAlt: 'Audio note with speaker-labeled transcript',
  },
  {
    icon: '\u{1F9E0}',
    title: 'Multi-Backend STT',
    description: 'Whisper, NeMo Parakeet & Canary, VibeVoice-ASR, and whisper.cpp — your choice.',
    screenshot: multibackendImg,
    screenshotAlt: 'Server config showing multiple backend options',
  },
  {
    icon: '\u{1F310}',
    title: 'Remote Access',
    description: 'Access your home GPU from anywhere via Tailscale or share on your local network.',
    screenshot: remoteImg,
    screenshotAlt: 'Server configuration with remote connection settings',
  },
  {
    icon: '\u{1F4BB}',
    title: 'Cross-Platform',
    description: 'Linux, Windows 11, and macOS with native Apple Silicon (Metal) support.',
    screenshot: crossplatformImg,
    screenshotAlt: 'Server configuration showing setup status',
  },
  {
    icon: '\u{1F916}',
    title: 'LM Studio Integration',
    description: 'Chat with a local AI about your transcription notes via LM Studio.',
    screenshot: lmstudioImg,
    screenshotAlt: 'Notebook view with LM Studio chat panel',
  },
];
---

<section id="features" class="animate-fade-in-up px-6 py-16 md:py-24">
  <div class="mx-auto max-w-5xl">
    <!-- Section header -->
    <div class="mb-10 text-center">
      <p class="mb-2 text-xs font-medium uppercase tracking-widest text-accent-magenta">
        Features
      </p>
      <h2 class="text-2xl font-semibold text-white md:text-3xl">Everything You Need</h2>
    </div>

    <!-- 3x3 Grid -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {features.map((feature, i) => (
        <FeatureCard
          icon={feature.icon}
          title={feature.title}
          description={feature.description}
          screenshot={feature.screenshot}
          screenshotAlt={feature.screenshotAlt}
          delay={i * 50}
        />
      ))}
    </div>
  </div>
</section>
```

- [ ] **Step 3: Add FeatureGrid to index.astro**

Update `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import Hero from '../components/Hero.astro';
import FeatureGrid from '../components/FeatureGrid.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <Hero />
    <FeatureGrid />
  </main>
</BaseLayout>
```

- [ ] **Step 4: Verify in dev server**

Verify: "Features" section with magenta label, 3-column grid on desktop, 2-column on tablet, 1-column on mobile. Each card has screenshot thumbnail, icon + title, description. Cards stagger-fade-in on scroll. Hover brightens border.

- [ ] **Step 5: Commit**

```bash
git add src/components/FeatureCard.astro src/components/FeatureGrid.astro src/pages/index.astro
git commit -m "feat: add 3x3 feature grid with glass cards and staggered scroll animation"
```

---

## Task 6: VideoCard and VideoSection Components

**Files:**
- Create: `src/components/VideoCard.astro`
- Create: `src/components/VideoSection.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create VideoCard.astro**

Create `src/components/VideoCard.astro`:

```astro
---
interface Props {
  title: string;
  description: string;
  videoSrc: string;
  posterSrc?: string;
}

const { title, description, videoSrc, posterSrc } = Astro.props;
---

<div class="overflow-hidden rounded-xl border border-glass-border bg-glass-100">
  <!-- Video area -->
  <div class="group relative">
    <video
      class="w-full cursor-pointer"
      preload="metadata"
      controls
      poster={posterSrc}
    >
      <source src={videoSrc} type="video/webm" />
      Your browser does not support the video tag.
    </video>
    <!-- Play overlay (hidden when controls are active, CSS-only) -->
    <div class="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/20 opacity-100 transition-opacity group-hover:opacity-0">
      <div class="flex h-14 w-14 items-center justify-center rounded-full bg-white/15 backdrop-blur-sm transition-transform hover:scale-110">
        <svg class="h-6 w-6 text-white ml-0.5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 5v14l11-7z" />
        </svg>
      </div>
    </div>
  </div>
  <!-- Info -->
  <div class="p-4">
    <h3 class="text-sm font-semibold text-white">{title}</h3>
    <p class="mt-1 text-xs text-slate-400">{description}</p>
  </div>
</div>
```

- [ ] **Step 2: Create VideoSection.astro**

Create `src/components/VideoSection.astro`:

```astro
---
import VideoCard from './VideoCard.astro';

// R2 public URLs — update these after first R2 upload
const R2_BASE = 'https://assets.transcriptionsuite.com/videos';

const videos = [
  {
    title: 'App Tour',
    description: 'A full walkthrough of all features — session, notebook, server config, and more.',
    videoSrc: `${R2_BASE}/tour.webm`,
  },
  {
    title: 'Quick Start',
    description: 'From installation to your first transcription in under a minute.',
    videoSrc: `${R2_BASE}/quickstart.webm`,
  },
];
---

<section id="videos" class="animate-fade-in-up px-6 py-16 md:py-24">
  <div class="mx-auto max-w-4xl">
    <!-- Section header -->
    <div class="mb-10 text-center">
      <p class="mb-2 text-xs font-medium uppercase tracking-widest text-accent-orange">
        See It In Action
      </p>
      <h2 class="text-2xl font-semibold text-white md:text-3xl">Tour &amp; How-To</h2>
    </div>

    <!-- 2-column grid -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {videos.map((video) => (
        <VideoCard
          title={video.title}
          description={video.description}
          videoSrc={video.videoSrc}
        />
      ))}
    </div>
  </div>
</section>
```

- [ ] **Step 3: Add VideoSection to index.astro**

Update `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import Hero from '../components/Hero.astro';
import FeatureGrid from '../components/FeatureGrid.astro';
import VideoSection from '../components/VideoSection.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <Hero />
    <FeatureGrid />
    <VideoSection />
  </main>
</BaseLayout>
```

- [ ] **Step 4: Verify in dev server**

Verify: "See It In Action" section with orange label, two video cards side by side on desktop, stacked on mobile. Video cards show play button overlay. Videos won't load yet (R2 URLs not set up) — the `<video>` element will show an empty state, which is expected.

- [ ] **Step 5: Commit**

```bash
git add src/components/VideoCard.astro src/components/VideoSection.astro src/pages/index.astro
git commit -m "feat: add video section with glass cards and R2 video references"
```

---

## Task 7: AboutSection Component

**Files:**
- Create: `src/components/AboutSection.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create AboutSection.astro**

Create `src/components/AboutSection.astro`:

```astro
<section id="about" class="animate-fade-in-up px-6 py-16 md:py-24">
  <div class="mx-auto max-w-3xl">
    <!-- Section header -->
    <div class="mb-8 text-center">
      <p class="mb-2 text-xs font-medium uppercase tracking-widest text-accent-cyan">
        The Story
      </p>
      <h2 class="text-2xl font-semibold text-white md:text-3xl">About This Project</h2>
    </div>

    <!-- Glass card with story -->
    <div class="rounded-xl border border-glass-border bg-glass-100 p-6 md:p-8">
      <div class="space-y-4 text-sm leading-relaxed text-slate-300">
        <p>
          TranscriptionSuite started as a personal tool and turned into a hobby project.
          I&rsquo;m an engineer &mdash; just not a <em>software</em> engineer.
          This whole thing is vibecoded, but not blindly: for example, Dockerizing
          the server for easy distribution was 100% my idea.
        </p>
        <p>
          I&rsquo;m using this project to learn programming. Starting from virtually
          nothing, I now have a decent grasp of Python, git, uv &amp; Docker. I started
          doing this because it&rsquo;s fun, not to make money &mdash; though I do find,
          despite my mechanical engineering degree, that I want to follow software as a career.
        </p>
        <p>
          Since I dogfood the app every day, I&rsquo;m not going to abandon it.
          I&rsquo;ll also try to deal with bugs as soon as possible.
        </p>
        <p class="text-slate-400">
          Inspired by
          <a
            href="https://github.com/KoljaB/RealtimeSTT"
            target="_blank"
            rel="noopener noreferrer"
            class="text-accent-cyan hover:underline"
          >
            RealtimeSTT
          </a>.
        </p>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 2: Add AboutSection to index.astro**

Update `src/pages/index.astro`:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import Hero from '../components/Hero.astro';
import FeatureGrid from '../components/FeatureGrid.astro';
import VideoSection from '../components/VideoSection.astro';
import AboutSection from '../components/AboutSection.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <Hero />
    <FeatureGrid />
    <VideoSection />
    <AboutSection />
  </main>
</BaseLayout>
```

- [ ] **Step 3: Verify in dev server**

Verify: "The Story" section with cyan label, glass card containing the about text. RealtimeSTT link is cyan and opens in new tab.

- [ ] **Step 4: Commit**

```bash
git add src/components/AboutSection.astro src/pages/index.astro
git commit -m "feat: add about section with project origin story"
```

---

## Task 8: GitHubCTA and Footer Components

**Files:**
- Create: `src/components/GitHubCTA.astro`
- Create: `src/components/Footer.astro`
- Modify: `src/pages/index.astro`

- [ ] **Step 1: Create GitHubCTA.astro**

Create `src/components/GitHubCTA.astro`:

```astro
---
const githubUrl = 'https://github.com/homelab-00/TranscriptionSuite';
---

<section class="animate-fade-in-up bg-gradient-to-b from-transparent to-accent-cyan/5 px-6 py-16 md:py-24">
  <div class="mx-auto max-w-2xl text-center">
    <h2 class="mb-3 text-2xl font-bold text-white md:text-3xl">Open Source &amp; Free</h2>
    <p class="mb-8 text-sm text-slate-400">
      Star the repo, report bugs, or contribute
    </p>
    <a
      href={githubUrl}
      target="_blank"
      rel="noopener noreferrer"
      class="inline-flex items-center gap-2 rounded-lg bg-accent-cyan px-8 py-3 text-sm font-semibold text-slate-900 transition-opacity hover:opacity-90"
    >
      <svg class="h-5 w-5" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
      </svg>
      View on GitHub
    </a>
  </div>
</section>
```

- [ ] **Step 2: Create Footer.astro**

Create `src/components/Footer.astro`:

```astro
<footer class="border-t border-white/5 px-6 py-6">
  <div class="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 text-xs text-slate-600 sm:flex-row">
    <span>&copy; {new Date().getFullYear()} homelab-00</span>
    <span>Built with Astro &middot; Hosted on Cloudflare</span>
  </div>
</footer>
```

- [ ] **Step 3: Add both to index.astro**

Update `src/pages/index.astro` to its final form:

```astro
---
import BaseLayout from '../layouts/BaseLayout.astro';
import Navbar from '../components/Navbar.astro';
import Hero from '../components/Hero.astro';
import FeatureGrid from '../components/FeatureGrid.astro';
import VideoSection from '../components/VideoSection.astro';
import AboutSection from '../components/AboutSection.astro';
import GitHubCTA from '../components/GitHubCTA.astro';
import Footer from '../components/Footer.astro';
import '../styles/global.css';
---

<BaseLayout
  title="TranscriptionSuite — Local, Private Speech-to-Text"
  description="Fully local and private speech-to-text app with speaker diarization, audio notebook, and multi-backend STT. Runs entirely on your machine."
>
  <Navbar />
  <main>
    <Hero />
    <FeatureGrid />
    <VideoSection />
    <AboutSection />
    <GitHubCTA />
  </main>
  <Footer />
</BaseLayout>
```

- [ ] **Step 4: Verify in dev server**

Verify: Full page scroll — Hero → Features → Videos → About → GitHub CTA → Footer. All nav links scroll to correct sections. CTA button links to GitHub. Footer shows copyright and "Built with Astro" text.

- [ ] **Step 5: Commit**

```bash
git add src/components/GitHubCTA.astro src/components/Footer.astro src/pages/index.astro
git commit -m "feat: add GitHub CTA section and footer, complete page layout"
```

---

## Task 9: Final Polish and Build Verification

**Files:**
- Modify: `src/styles/global.css` (if needed)
- Modify: `src/components/Hero.astro` (gradient fix if needed)

- [ ] **Step 1: Run production build**

```bash
cd /home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage
npm run build
```

Expected: Clean build with no errors. Output in `dist/`.

- [ ] **Step 2: Preview production build**

```bash
npm run preview
```

Open the preview URL. Verify the full page end-to-end:

1. Navbar sticks on scroll, glass blur visible
2. Hero gradient text renders correctly (not plain text)
3. Hero screenshot floats
4. Feature cards fade in staggered on scroll
5. Video section visible (videos won't play without R2 yet)
6. About section scrolls in
7. GitHub CTA button works
8. Footer visible at bottom
9. Mobile: hamburger menu works, grid collapses correctly
10. Selection color is cyan on dark

- [ ] **Step 3: Fix any issues found in Step 2**

Address any visual or functional issues discovered during the preview check.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: polish visual issues from production preview"
```

Skip this commit if no fixes were needed.

---

## Task 10: Push to GitHub

**Files:** None (git operations only)

- [ ] **Step 1: Create GitHub repo**

```bash
gh repo create homelab-00/TranscriptionSuite_Webpage --public --source=/home/Bill/Code_Projects/TypeScript_Projects/TranscriptionSuite_Webpage --push
```

Expected: Repo created and all commits pushed to `main`.

- [ ] **Step 2: Verify repo on GitHub**

```bash
gh repo view homelab-00/TranscriptionSuite_Webpage --web
```

Verify: All files visible, commits present.

---

## Task 11: Playwright Screenshot Script (App Repo)

**Files (in app repo `/home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/`):**
- Create: `scripts/webpage-assets/capture-screenshots.ts`
- Create: `scripts/webpage-assets/playwright.config.ts`
- Modify: `package.json` (add `@playwright/test` as devDependency at project root — or install locally in `scripts/webpage-assets/`)

- [ ] **Step 1: Set up Playwright in app repo**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
mkdir -p scripts/webpage-assets
cd scripts/webpage-assets
npm init -y
npm install --save-dev @playwright/test
```

- [ ] **Step 2: Create Playwright config**

Create `scripts/webpage-assets/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: ['capture-screenshots.ts', 'record-videos.ts'],
  timeout: 120_000,
  use: {
    trace: 'off',
  },
});
```

- [ ] **Step 3: Create screenshot capture script**

Create `scripts/webpage-assets/capture-screenshots.ts`:

```ts
import { test, _electron as electron } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

const DASHBOARD_PATH = path.resolve(__dirname, '../../dashboard');
const DEFAULT_OUTPUT = path.resolve(
  __dirname,
  '../../../TypeScript_Projects/TranscriptionSuite_Webpage/src/assets/screenshots'
);

const OUTPUT_DIR = process.env.SCREENSHOT_OUTPUT_DIR || DEFAULT_OUTPUT;

// Each screenshot: a name and a function describing how to navigate to that state.
const screenshots: Array<{
  name: string;
  navigate: (page: import('@playwright/test').Page) => Promise<void>;
}> = [
  {
    name: 'hero',
    navigate: async (page) => {
      // Session view is the default — just wait for it to load
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-longform',
    navigate: async (page) => {
      // Session view with transcription result — click Session tab
      await page.click('[data-testid="nav-session"], text=Session');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-live',
    navigate: async (page) => {
      // Session view — Live Mode section is visible by default
      await page.click('[data-testid="nav-session"], text=Session');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-notebook',
    navigate: async (page) => {
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-diarization',
    navigate: async (page) => {
      // Navigate to notebook, then open a note if one exists
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-multibackend',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-remote',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-crossplatform',
    navigate: async (page) => {
      await page.click('[data-testid="nav-server"], text=Server');
      await page.waitForLoadState('networkidle');
    },
  },
  {
    name: 'feature-lmstudio',
    navigate: async (page) => {
      await page.click('[data-testid="nav-notebook"], text=Notebook');
      await page.waitForLoadState('networkidle');
    },
  },
];

test('capture all landing page screenshots', async () => {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const electronApp = await electron.launch({
    args: [path.join(DASHBOARD_PATH, 'dist-electron/main.js')],
    cwd: DASHBOARD_PATH,
  });

  const page = await electronApp.firstWindow();
  await page.waitForLoadState('networkidle');
  // Give the app a moment to render fully
  await page.waitForTimeout(2000);

  for (const shot of screenshots) {
    await shot.navigate(page);
    await page.waitForTimeout(500); // settle time
    await page.screenshot({
      path: path.join(OUTPUT_DIR, `${shot.name}.png`),
      type: 'png',
    });
  }

  await electronApp.close();
});
```

- [ ] **Step 4: Test the script runs (requires built dashboard + backend)**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/scripts/webpage-assets
npx playwright test capture-screenshots.ts
```

Expected: 9 screenshots written to the webpage repo's `src/assets/screenshots/` directory. If the dashboard isn't built or the backend isn't running, the script will fail with a clear error — that's expected and acceptable.

- [ ] **Step 5: Commit**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git add scripts/webpage-assets/
git commit -m "feat(webpage-assets): add Playwright screenshot capture script for landing page"
```

---

## Task 12: Playwright Video Recording Script (App Repo)

**Files (in app repo):**
- Create: `scripts/webpage-assets/record-videos.ts`

- [ ] **Step 1: Create video recording script**

Create `scripts/webpage-assets/record-videos.ts`:

```ts
import { test, _electron as electron } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

const DASHBOARD_PATH = path.resolve(__dirname, '../../dashboard');
const DEFAULT_OUTPUT = path.resolve(__dirname, 'output/videos');

const OUTPUT_DIR = process.env.VIDEO_OUTPUT_DIR || DEFAULT_OUTPUT;

async function recordSession(
  name: string,
  actions: (page: import('@playwright/test').Page) => Promise<void>
) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const electronApp = await electron.launch({
    args: [path.join(DASHBOARD_PATH, 'dist-electron/main.js')],
    cwd: DASHBOARD_PATH,
    recordVideo: {
      dir: OUTPUT_DIR,
      size: { width: 1280, height: 720 },
    },
  });

  const page = await electronApp.firstWindow();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  await actions(page);

  await page.close(); // triggers video save
  await electronApp.close();

  // Rename the auto-generated video file to our desired name
  const files = fs.readdirSync(OUTPUT_DIR).filter((f) => f.endsWith('.webm'));
  const newest = files
    .map((f) => ({ f, mtime: fs.statSync(path.join(OUTPUT_DIR, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime)[0];

  if (newest) {
    const dest = path.join(OUTPUT_DIR, `${name}.webm`);
    fs.renameSync(path.join(OUTPUT_DIR, newest.f), dest);
  }
}

test('record app tour video', async () => {
  await recordSession('tour', async (page) => {
    // Session tab — already here by default
    await page.waitForTimeout(3000);

    // Click Notebook tab
    await page.click('[data-testid="nav-notebook"], text=Notebook');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Click Server tab
    await page.click('[data-testid="nav-server"], text=Server');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Back to Session
    await page.click('[data-testid="nav-session"], text=Session');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
  });
});

test('record quickstart video', async () => {
  await recordSession('quickstart', async (page) => {
    // Server tab
    await page.click('[data-testid="nav-server"], text=Server');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);

    // Session tab
    await page.click('[data-testid="nav-session"], text=Session');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(3000);
  });
});
```

- [ ] **Step 2: Commit**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git add scripts/webpage-assets/record-videos.ts
git commit -m "feat(webpage-assets): add Playwright video recording script for landing page"
```

---

## Task 13: Asset Sync Script (App Repo)

**Files (in app repo):**
- Create: `scripts/webpage-assets/sync-assets.sh`

- [ ] **Step 1: Create sync script**

Create `scripts/webpage-assets/sync-assets.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBPAGE_REPO="${1:-$(realpath "$SCRIPT_DIR/../../../TypeScript_Projects/TranscriptionSuite_Webpage")}"
R2_BUCKET="${R2_BUCKET:-transcriptionsuite-assets}"

echo "=== Webpage repo: ${WEBPAGE_REPO} ==="
echo "=== R2 bucket:    ${R2_BUCKET} ==="
echo ""

# Check the webpage repo exists
if [ ! -d "$WEBPAGE_REPO/src/assets/screenshots" ]; then
  echo "ERROR: Webpage repo not found at ${WEBPAGE_REPO}"
  echo "Usage: $0 [path-to-webpage-repo]"
  exit 1
fi

echo "=== Step 1: Capturing screenshots ==="
cd "$SCRIPT_DIR"
SCREENSHOT_OUTPUT_DIR="${WEBPAGE_REPO}/src/assets/screenshots" npx playwright test capture-screenshots.ts
echo ""

echo "=== Step 2: Recording videos ==="
npx playwright test record-videos.ts
echo ""

echo "=== Step 3: Uploading videos to R2 ==="
if ! command -v wrangler &> /dev/null; then
  echo "WARNING: wrangler CLI not found. Skipping R2 upload."
  echo "Install with: npm install -g wrangler"
  echo "Then run: wrangler r2 object put ${R2_BUCKET}/videos/<file> --file <path>"
else
  for f in "$SCRIPT_DIR/output/videos"/*.webm; do
    [ -f "$f" ] || continue
    echo "Uploading $(basename "$f")..."
    wrangler r2 object put "${R2_BUCKET}/videos/$(basename "$f")" --file "$f"
  done
fi
echo ""

echo "=== Done ==="
echo "Screenshots → ${WEBPAGE_REPO}/src/assets/screenshots/"
echo "Videos      → R2 bucket '${R2_BUCKET}' (if wrangler was available)"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite/scripts/webpage-assets/sync-assets.sh
```

- [ ] **Step 3: Commit**

```bash
cd /home/Bill/Code_Projects/Python_Projects/TranscriptionSuite
git add scripts/webpage-assets/sync-assets.sh
git commit -m "feat(webpage-assets): add asset sync script (screenshots + videos + R2 upload)"
```

---

## Task Summary

| Task | Repo | Description |
|------|------|-------------|
| 1 | Webpage | Scaffold Astro + Tailwind v4 + design tokens |
| 2 | Webpage | BaseLayout with meta, fonts, scroll animations |
| 3 | Webpage | Sticky frosted-glass navbar with mobile hamburger |
| 4 | Webpage | Hero with gradient headline, CTAs, framed screenshot |
| 5 | Webpage | 3x3 feature grid with glass cards |
| 6 | Webpage | Video section with R2-backed video cards |
| 7 | Webpage | About section with project origin story |
| 8 | Webpage | GitHub CTA section + footer |
| 9 | Webpage | Final polish and production build verification |
| 10 | Webpage | Push to GitHub |
| 11 | App | Playwright screenshot capture script |
| 12 | App | Playwright video recording script |
| 13 | App | Asset sync shell script |
