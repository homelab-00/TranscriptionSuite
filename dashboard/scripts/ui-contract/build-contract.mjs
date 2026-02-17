#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';
import { PROJECT_ROOT } from './shared.mjs';

const factsPath = path.join(PROJECT_ROOT, 'ui-contract', '.generated', 'extracted-facts.json');
const outputPath = path.join(PROJECT_ROOT, 'ui-contract', 'transcription-suite-ui.contract.yaml');

const facts = JSON.parse(fs.readFileSync(factsPath, 'utf8'));

const componentSpecs = {
  App: {
    required_tokens: ['colors', 'motion', 'layout', 'typography', 'z_index'],
    allowed_variants: { view: ['SESSION', 'NOTEBOOK', 'SERVER'] },
    structural_invariants: [
      {
        id: 'app-shell',
        rule: 'Preserve 2-pane app shell with persistent sidebar, content main, and modal mounts at root level.',
      },
    ],
    behavior_rules: [
      {
        id: 'view-transition',
        rule: 'View container transitions must use approved animate/fade/slide utility classes and contract motion durations.',
      },
    ],
    state_rules: [
      {
        id: 'current-view-routing',
        rule: 'Only SESSION, NOTEBOOK, SERVER view states are allowed for top-level routing.',
      },
    ],
  },
  Sidebar: {
    required_tokens: ['glass', 'colors', 'motion', 'radii', 'shadows', 'z_index'],
    allowed_variants: {
      collapsed: ['true', 'false'],
      active_view: ['SESSION', 'NOTEBOOK', 'SERVER'],
    },
    structural_invariants: [
      {
        id: 'sidebar-width-modes',
        rule: 'Sidebar must keep collapsed/expanded width modes and preserve active navigation pill with cyan indicator.',
      },
    ],
    behavior_rules: [
      {
        id: 'collapse-motion',
        rule: 'Collapse/expand and active pill transitions must remain within approved duration/easing tokens.',
      },
    ],
    state_rules: [
      {
        id: 'status-dots',
        rule: 'Client and server nav items retain StatusLight indicators and active/inactive styling behavior.',
      },
    ],
  },
  AudioVisualizer: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows'],
    allowed_variants: { mode: ['embedded', 'fullscreen'] },
    structural_invariants: [
      {
        id: 'canvas-layering',
        rule: 'Canvas visualizer keeps grid overlay, bordered surface, and rounded container hierarchy.',
      },
    ],
    behavior_rules: [
      {
        id: 'raf-loop',
        rule: 'Visualizer animation must run via requestAnimationFrame and retain layered cyan/magenta/orange wave rendering.',
      },
    ],
    state_rules: [
      {
        id: 'responsive-resize',
        rule: 'Canvas dimensions must track parent element resize behavior before drawing frames.',
      },
    ],
  },
  Button: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'blur'],
    allowed_variants: {
      variant: ['primary', 'secondary', 'danger', 'ghost', 'glass'],
      size: ['sm', 'md', 'lg', 'icon'],
    },
    structural_invariants: [
      {
        id: 'button-base',
        rule: 'All button variants inherit shared base class stack for radius, typography, transitions, and disabled behavior.',
      },
    ],
    behavior_rules: [
      {
        id: 'button-motion',
        rule: 'Button hover/active/disabled transitions use only approved duration/easing and scale classes.',
      },
    ],
    state_rules: [
      {
        id: 'variant-closed-set',
        rule: 'Only declared variant/size combinations are allowed without contract/version update.',
      },
    ],
  },
  GlassCard: {
    required_tokens: ['glass', 'colors', 'radii', 'shadows', 'blur'],
    allowed_variants: { header: ['with_header', 'without_header'] },
    structural_invariants: [
      {
        id: 'glass-card-shell',
        rule: 'GlassCard preserves gradient glass shell, optional header row, and content body region.',
      },
    ],
    behavior_rules: [
      {
        id: 'surface-consistency',
        rule: 'Glass surface gradients, border strength, and shadow depth stay within registered token values.',
      },
    ],
    state_rules: [
      {
        id: 'header-optional',
        rule: 'Title/action header is optional but when present must retain h-14 bordered header pattern.',
      },
    ],
  },
  AppleSwitch: {
    required_tokens: ['colors', 'motion', 'radii', 'spacing_and_size_constraints'],
    allowed_variants: { size: ['sm', 'md'], checked: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'switch-geometry',
        rule: 'Switch track and knob dimensions/translations remain tied to current sm/md geometry math.',
      },
    ],
    behavior_rules: [
      {
        id: 'switch-transition',
        rule: 'Switch color and knob transform transitions use approved duration/easing tokens only.',
      },
    ],
    state_rules: [
      {
        id: 'focus-ring',
        rule: 'Focusable switch keeps cyan ring and slate offset ring styling for keyboard visibility.',
      },
    ],
  },
  CustomSelect: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'z_index'],
    allowed_variants: { accentColor: ['cyan', 'magenta'], isOpen: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'portal-dropdown',
        rule: 'Dropdown content must render in portal with fixed positioning and approved z-index layer.',
      },
    ],
    behavior_rules: [
      {
        id: 'open-close-motion',
        rule: 'Chevron rotation and dropdown open animation remain constrained to approved motion tokens.',
      },
    ],
    state_rules: [
      {
        id: 'active-option-dot',
        rule: 'Selected option indicator dot color/shadow must follow accentColor variant mapping.',
      },
    ],
  },
  StatusLight: {
    required_tokens: ['colors', 'motion', 'shadows', 'status_states'],
    allowed_variants: {
      status: ['active', 'inactive', 'warning', 'error', 'loading'],
      animate: ['true', 'false'],
    },
    structural_invariants: [
      {
        id: 'two-layer-light',
        rule: 'Status light keeps base dot and optional ping halo layers with same circular geometry.',
      },
    ],
    behavior_rules: [
      {
        id: 'clock-sync-ping',
        rule: 'Animated non-inactive states preserve system-clock synchronized ping offset behavior.',
      },
    ],
    state_rules: [
      {
        id: 'status-color-map',
        rule: 'Each status maps to registered bg/shadow token pair and cannot drift from status palette.',
      },
    ],
  },
  LogTerminal: {
    required_tokens: ['colors', 'typography', 'radii', 'shadows', 'scrollbar'],
    allowed_variants: { color: ['cyan', 'magenta', 'orange'] },
    structural_invariants: [
      {
        id: 'terminal-layout',
        rule: 'Terminal keeps bordered shell with header row and custom-scrollbar scroll body.',
      },
    ],
    behavior_rules: [
      {
        id: 'auto-scroll',
        rule: 'Log append behavior must preserve automatic scroll-to-bottom synchronization.',
      },
    ],
    state_rules: [
      {
        id: 'log-type-colors',
        rule: 'Info/success/warning/error message coloring remains bound to approved text tokens.',
      },
    ],
  },
  SessionView: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'blur',
      'scrollbar',
      'status_states',
    ],
    allowed_variants: {
      audioSource: ['mic', 'system'],
      showLogs: ['true', 'false'],
      isLive: ['true', 'false'],
      isMuted: ['true', 'false'],
      isFullscreenVisualizerOpen: ['true', 'false'],
      serverRunning: ['true', 'false'],
      clientConnected: ['true', 'false'],
    },
    structural_invariants: [
      {
        id: 'two-column-session-layout',
        rule: 'Session view preserves left controls/right monitoring split with scroll indicators and masked corners.',
      },
      {
        id: 'scroll-indicator-offset',
        rule: 'Scroll fade indicators and corner masks must use right-3 (0.75rem) offset to align with the scrollbar track width plus padding, matching the original mockup layout.',
      },
      {
        id: 'live-mode-min-height',
        rule: 'Live Mode GlassCard must use min-h-[calc(100vh-30rem)] to ensure the offline placeholder text centers properly within the transcript area.',
      },
    ],
    behavior_rules: [
      {
        id: 'logs-drawer-animation',
        rule: 'Bottom logs drawer open/close behavior remains tied to approved durations and easing curves.',
      },
      {
        id: 'scroll-shadow-updates',
        rule: 'Scroll indicator opacity behavior must continue to derive from top/bottom scroll state checks.',
      },
    ],
    state_rules: [
      {
        id: 'health-accent-state',
        rule: 'Healthy system state keeps cyan border/glow emphasis on control center card only when both statuses active.',
      },
    ],
  },
  NotebookView: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'blur',
      'scrollbar',
      'z_index',
    ],
    allowed_variants: { activeTab: ['CALENDAR', 'SEARCH', 'IMPORT'] },
    structural_invariants: [
      {
        id: 'tabbed-notebook-shell',
        rule: 'Notebook view keeps top tab switcher and single active content surface with modal mounts.',
      },
    ],
    behavior_rules: [
      {
        id: 'tab-content-animation',
        rule: 'Tab content transition classes and month navigation animations stay within approved motion tokens.',
      },
    ],
    state_rules: [
      {
        id: 'tab-state-closed-set',
        rule: 'Only CALENDAR, SEARCH, IMPORT tab states are allowed for notebook routing.',
      },
    ],
  },
  ServerView: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'scrollbar',
      'status_states',
    ],
    allowed_variants: {
      imageStatus: ['active', 'inactive'],
      status: ['active', 'stopped', 'removed'],
    },
    structural_invariants: [
      {
        id: 'timeline-cards',
        rule: 'Server configuration remains a vertical timeline of numbered glass cards with icon nodes.',
      },
    ],
    behavior_rules: [
      {
        id: 'status-accent-transitions',
        rule: 'Image/container status accents and opacity transitions are constrained to approved duration/ease tokens.',
      },
    ],
    state_rules: [
      {
        id: 'removed-disable-pattern',
        rule: 'Removed state keeps dimmed/pointer-disabled configuration areas instead of hard removal.',
      },
    ],
  },
  SettingsModal: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'blur',
      'scrollbar',
      'z_index',
    ],
    allowed_variants: {
      activeTab: ['App', 'Client', 'Server', 'Notebook'],
      isOpen: ['true', 'false'],
      isVisible: ['true', 'false'],
    },
    structural_invariants: [
      {
        id: 'settings-modal-shell',
        rule: 'Settings modal preserves backdrop, fixed-height modal shell, tab header, scroll body, and footer actions.',
      },
    ],
    behavior_rules: [
      {
        id: 'modal-enter-exit',
        rule: 'Open/close and tab-pane animation classes use only approved durations and cubic-bezier easing tokens.',
      },
    ],
    state_rules: [
      {
        id: 'tab-closed-set',
        rule: 'Settings tab set is fixed to App/Client/Server/Notebook labels.',
      },
    ],
  },
  AboutModal: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'blur', 'z_index'],
    allowed_variants: { isOpen: ['true', 'false'], isVisible: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'about-modal-layout',
        rule: 'About modal keeps gradient banner, floating avatar, links grid, and footer section hierarchy.',
      },
    ],
    behavior_rules: [
      {
        id: 'about-modal-transition',
        rule: 'Backdrop and modal slide transitions remain bound to approved duration/ease tokens.',
      },
    ],
    state_rules: [
      {
        id: 'profile-badge',
        rule: 'Profile link indicator badge retains cyan accent and dark border treatment.',
      },
    ],
  },
  AudioNoteModal: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'blur',
      'scrollbar',
      'z_index',
    ],
    allowed_variants: {
      isOpen: ['true', 'false'],
      isVisible: ['true', 'false'],
      isSidebarOpen: ['true', 'false'],
      llmStatus: ['active', 'inactive'],
      summaryExpanded: ['true', 'false'],
      isPlaying: ['true', 'false'],
    },
    structural_invariants: [
      {
        id: 'split-modal-layout',
        rule: 'AudioNote modal keeps left transcript/player pane and optional right LM sidebar pane in a single shell.',
      },
    ],
    behavior_rules: [
      {
        id: 'sidebar-slide',
        rule: 'LM sidebar open/close width and translate transitions stay within approved motion set.',
      },
      {
        id: 'summary-stream-state',
        rule: 'Summary generation state keeps progressive text reveal and cursor pulse behavior.',
      },
    ],
    state_rules: [
      {
        id: 'context-menu-layer',
        rule: 'Session context menu remains on top portal layer and uses approved dropdown motion tokens.',
      },
    ],
  },
  AddNoteModal: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'blur',
      'scrollbar',
      'z_index',
    ],
    allowed_variants: { isOpen: ['true', 'false'], isVisible: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'add-note-shell',
        rule: 'Add-note modal keeps header, upload dropzone, options card, and footer action structure.',
      },
    ],
    behavior_rules: [
      {
        id: 'modal-scale-fade',
        rule: 'Open/close modal uses approved scale/opacity/translate transitions and timing tokens.',
      },
    ],
    state_rules: [
      {
        id: 'option-switches',
        rule: 'Import option toggles remain AppleSwitch-based with current labels and descriptions.',
      },
    ],
  },
  FullscreenVisualizer: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'blur', 'z_index'],
    allowed_variants: { isOpen: ['true', 'false'], isVisible: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'fullscreen-hud-layout',
        rule: 'Fullscreen visualizer keeps backdrop layer, top HUD, main visualizer region, and bottom stats grid.',
      },
    ],
    behavior_rules: [
      {
        id: 'fullscreen-entry',
        rule: 'Fullscreen shell and staged reveal animations must stay within approved 500/700ms timing family.',
      },
    ],
    state_rules: [
      {
        id: 'hud-accent-system',
        rule: 'HUD cards and live indicators keep cyan/magenta/orange/blue role mapping from contract palette.',
      },
    ],
  },
  NoteActionMenu: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'blur', 'z_index'],
    allowed_variants: { trigger_type: ['rect', 'point'] },
    structural_invariants: [
      {
        id: 'context-menu-portal',
        rule: 'Context menu renders in portal overlay with fixed absolute menu card anchored to trigger.',
      },
    ],
    behavior_rules: [
      {
        id: 'menu-slide-up',
        rule: 'Menu entry animation uses slideUpFromBottomEdge keyframe and approved cubic-bezier timing.',
      },
    ],
    state_rules: [
      {
        id: 'danger-action-slot',
        rule: 'Delete action keeps destructive red treatment separate from neutral actions.',
      },
    ],
  },
  HistoryPicker: {
    required_tokens: ['colors', 'motion', 'radii', 'shadows', 'blur', 'z_index'],
    allowed_variants: { isOpen: ['true', 'false'], isVisible: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'year-month-grid',
        rule: 'History picker keeps centered year controls and 3-column month button grid.',
      },
    ],
    behavior_rules: [
      {
        id: 'picker-fade-scale',
        rule: 'Picker open/close uses opacity/scale/translate transitions with approved cubic-bezier easing.',
      },
    ],
    state_rules: [
      {
        id: 'current-month-indicator',
        rule: 'Current month indicator dot remains cyan when month is not currently selected.',
      },
    ],
  },
  TimeSection: {
    required_tokens: [
      'glass',
      'colors',
      'motion',
      'radii',
      'shadows',
      'scrollbar',
      'spacing_and_size_constraints',
    ],
    allowed_variants: { visibleSlots: ['2', '3', '4'] },
    structural_invariants: [
      {
        id: 'hour-lane-layout',
        rule: 'TimeSection keeps sticky hour column and horizontal snapping event lane with add-note slot.',
      },
    ],
    behavior_rules: [
      {
        id: 'card-hover-motion',
        rule: 'Event card hover/active transforms must remain within approved transition and scale values.',
      },
    ],
    state_rules: [
      {
        id: 'compact-density-mode',
        rule: 'Compact mode behavior is governed by visibleSlots threshold and keeps AI/duration collapse behavior.',
      },
    ],
  },
  CalendarTab: {
    required_tokens: ['glass', 'colors', 'motion', 'radii', 'shadows', 'z_index'],
    allowed_variants: { slideDirection: ['left', 'right', 'null'], visibleSlots: ['2', '3', '4'] },
    structural_invariants: [
      {
        id: 'calendar-plus-time-sections',
        rule: 'Calendar tab keeps month grid pane plus morning/afternoon TimeSection stack.',
      },
    ],
    behavior_rules: [
      {
        id: 'month-slide-motion',
        rule: 'Month navigation maintains slideInRight/slideInLeft keyframe classes and 0.3s easing profile.',
      },
    ],
    state_rules: [
      {
        id: 'jan-highlight',
        rule: 'Highlighted January event count and selected-day treatment remain explicit in current mock data states.',
      },
    ],
  },
  SearchTab: {
    required_tokens: ['glass', 'colors', 'motion', 'radii', 'scrollbar'],
    allowed_variants: { result_count: ['0', '1_plus'] },
    structural_invariants: [
      {
        id: 'search-results-layout',
        rule: 'Search tab keeps top search input, filter row, and vertically stacked selectable result cards.',
      },
    ],
    behavior_rules: [
      {
        id: 'result-hover-motion',
        rule: 'Search result hover state is limited to approved transition-color token family.',
      },
    ],
    state_rules: [
      {
        id: 'selectable-body-copy',
        rule: 'Result content body remains selectable while metadata chrome remains non-selectable where defined.',
      },
    ],
  },
  ImportTab: {
    required_tokens: ['glass', 'colors', 'motion', 'radii', 'shadows'],
    allowed_variants: { upload_state: ['idle', 'hover'] },
    structural_invariants: [
      {
        id: 'dropzone-plus-options',
        rule: 'Import tab preserves dashed upload dropzone followed by import options glass card.',
      },
    ],
    behavior_rules: [
      {
        id: 'dropzone-hover',
        rule: 'Upload dropzone hover border/background/icon scaling remains constrained to approved transitions.',
      },
    ],
    state_rules: [
      {
        id: 'import-switch-options',
        rule: 'Speaker diarization and word timestamp option switches remain present in fixed order.',
      },
    ],
  },
  Section: {
    required_tokens: ['colors', 'radii', 'shadows'],
    allowed_variants: { section_type: ['settings_group'] },
    structural_invariants: [
      {
        id: 'section-shell',
        rule: 'Section helper keeps rounded container, uppercase heading row, and stacked content body.',
      },
    ],
    behavior_rules: [
      {
        id: 'section-static-motion',
        rule: 'Section helper itself does not introduce additional motion tokens beyond inherited children.',
      },
    ],
    state_rules: [
      {
        id: 'heading-divider',
        rule: 'Heading divider line remains part of section title structure.',
      },
    ],
  },
  CollapsibleSection: {
    required_tokens: ['colors', 'motion', 'radii'],
    allowed_variants: { isOpen: ['true', 'false'] },
    structural_invariants: [
      {
        id: 'collapsible-header-body',
        rule: 'CollapsibleSection keeps clickable header row and overflow-hidden content body container.',
      },
    ],
    behavior_rules: [
      {
        id: 'collapsible-motion',
        rule: 'Open/close height/opacity/rotation transitions remain tied to approved 200/300ms tokens.',
      },
    ],
    state_rules: [
      {
        id: 'open-accent',
        rule: 'Open state title accent remains magenta and chevron rotates with white highlighted background.',
      },
    ],
  },
  HudCard: {
    required_tokens: ['colors', 'radii', 'shadows', 'motion'],
    allowed_variants: { color: ['cyan', 'magenta', 'orange', 'blue'] },
    structural_invariants: [
      {
        id: 'hud-card-layout',
        rule: 'HUD card keeps icon capsule + text stack composition and border-backed glass surface.',
      },
    ],
    behavior_rules: [
      {
        id: 'hud-hover',
        rule: 'HUD hover visual response remains transition-color only and does not add new transform motion.',
      },
    ],
    state_rules: [
      {
        id: 'color-role-map',
        rule: 'HudCard color variants map to fixed accent token sets and must not accept ad hoc colors.',
      },
    ],
  },
};

const componentContracts = {};
for (const name of facts.components.names) {
  const spec = componentSpecs[name] || {
    required_tokens: ['colors', 'motion', 'radii', 'shadows'],
    allowed_variants: {},
    structural_invariants: [
      {
        id: 'structure-stable',
        rule: 'Preserve current structural layout and region hierarchy for this component.',
      },
    ],
    behavior_rules: [
      {
        id: 'motion-locked',
        rule: 'Use only approved motion tokens and classes from foundation token registry.',
      },
    ],
    state_rules: [
      {
        id: 'closed-set-styles',
        rule: 'Do not introduce unregistered utility, arbitrary, or inline style values.',
      },
    ],
  };

  componentContracts[name] = {
    file: facts.components.files[name],
    required_tokens: spec.required_tokens,
    allowed_variants: spec.allowed_variants,
    structural_invariants: spec.structural_invariants,
    behavior_rules: spec.behavior_rules,
    state_rules: spec.state_rules,
  };
}

const contract = {
  meta: {
    spec_version: '1.0.0',
    contract_mode: 'closed_set',
    source_scope: 'mockup_repo',
    validation_method: 'static_source_scan',
    generated_from: {
      repo_path: facts.repo_root,
      source_files: facts.source_files,
      generated_at: facts.generated_at,
      notes: 'Canonicalized from live source scan for React+TypeScript+Tailwind mockup.',
    },
  },
  foundation: {
    color_space: {
      policy: 'srgb_only',
      enforcement: 'postcss_plugin',
      plugin_name: 'strip-oklab-supports',
      rule: 'All Tailwind v4 @supports blocks that upgrade color rendering from sRGB fallbacks to oklab color-mix or oklab gradient interpolation must be stripped at build time. The original UI mockup (Tailwind v3 CDN) uses sRGB exclusively. Default palette shades are pinned to their Tailwind v3 hex values in @theme to prevent oklch gamut-mapping drift.',
      prohibited_css_functions: ['color-mix(in oklab, ...)', 'color-mix(in lab, ...)'],
      prohibited_color_spaces: ['oklch', 'oklab'],
    },
    tailwind: {
      dark_mode: facts.tailwind.dark_mode,
      font_family_sans: facts.tailwind.extend.fontFamily?.sans || [],
      accent_scale: facts.tokens.colors.accent_scale,
      glass_scale: facts.tokens.colors.glass_scale,
      backdrop_blur_scale: facts.tailwind.extend.backdropBlur || {},
    },
    tokens: {
      colors: {
        literal_palette: facts.tokens.colors.literal_palette,
        accent_scale: facts.tokens.colors.accent_scale,
        glass_scale: facts.tokens.colors.glass_scale,
        semantic_status_palette: facts.tokens.status_states.visual_mappings,
      },
      blur_levels: {
        backdrop: facts.tokens.blur_levels.backdrop,
        filter: facts.tokens.blur_levels.filter,
      },
      shadow_levels: {
        classes: facts.tokens.shadow_levels.classes,
      },
      motion: {
        duration_ms: facts.tokens.motion.duration_ms,
        easings: facts.tokens.motion.easings,
        keyframes: facts.tokens.motion.keyframes,
        animation_classes: facts.tokens.motion.animation_classes,
        animation_strings: facts.tokens.motion.animation_strings,
      },
      radii: {
        classes: facts.tokens.radii.classes,
      },
      z_index_levels: {
        classes: facts.tokens.z_index_levels.classes,
      },
      spacing_and_size_constraints: {
        arbitrary_classes: facts.tokens.spacing_and_size_constraints.arbitrary_classes,
      },
      status_states: {
        allowed: facts.tokens.status_states.allowed,
        visual_mappings: facts.tokens.status_states.visual_mappings,
      },
    },
  },
  global_behaviors: {
    css_blocks: {
      body: facts.global_css.body,
      selection: facts.global_css.selection,
      moz_selection: facts.global_css.moz_selection,
      selectable_text: facts.global_css.selectable_text,
      custom_scrollbar_root: facts.global_css.custom_scrollbar.root,
      custom_scrollbar_track: facts.global_css.custom_scrollbar.track,
      custom_scrollbar_thumb: facts.global_css.custom_scrollbar.thumb,
      custom_scrollbar_thumb_hover: facts.global_css.custom_scrollbar.thumb_hover,
      custom_scrollbar_corner: facts.global_css.custom_scrollbar.corner,
    },
    selection: {
      enforce_custom_selection: true,
      selectors: ['::selection', '::-moz-selection'],
      rationale: 'Maintain high-contrast cyan selection identity.',
    },
    text_selectability: {
      default_user_select: 'none',
      selectable_override_class: 'selectable-text',
      rule: 'Content remains non-selectable by default except explicit selectable regions.',
    },
    scrollbar: {
      opt_in_class: 'custom-scrollbar',
      rule: 'Scrollbar styling is opt-in and must use canonical WebKit selector blocks.',
    },
    portals: {
      required_z_layers: facts.tokens.z_index_levels.classes,
      rule: 'Portals and overlays must remain within declared z-index class set.',
    },
  },
  utility_allowlist: {
    exact_classes: facts.utilities.exact_classes,
    arbitrary_classes: facts.utilities.arbitrary_classes,
  },
  inline_style_allowlist: {
    allowed_properties: facts.inline_style.allowed_properties,
    allowed_literals: facts.inline_style.allowed_literals,
    keyframes: facts.inline_style.keyframes,
    animation_strings: facts.inline_style.animation_strings,
    cubic_beziers: facts.inline_style.cubic_beziers,
  },
  component_contracts: componentContracts,
  validation_policy: {
    unknown_utility_class: 'error',
    missing_required_field: 'error',
    missing_component_contract: 'error',
    semver_bump_required: 'error',
    notes: 'Closed-set enforcement for canonical mockup-derived renderer contract.',
  },
};

const yaml = YAML.stringify(contract, {
  indent: 2,
  lineWidth: 0,
  minContentWidth: 0,
});

fs.writeFileSync(outputPath, yaml, 'utf8');
process.stdout.write(`Wrote ${path.relative(PROJECT_ROOT, outputPath)}\n`);
