import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { ChevronDown, Search, Loader2, AlertTriangle, RefreshCw } from 'lucide-react';
import { apiClient } from '../../src/api/client';
import { AppleSwitch } from '../ui/AppleSwitch';
import type {
  ConfigField,
  ConfigSection,
  ConfigSubsection,
  ServerConfigTree,
} from '../../src/api/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ServerConfigEditorProps {
  /** Collected pending updates (path → value) managed by the parent. */
  pendingUpdates: Record<string, unknown>;
  /** Callback to register a changed value. */
  onFieldChange: (path: string, value: unknown) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse a field value from a text input back to its typed representation. */
function parseFieldValue(raw: string, field: ConfigField): unknown {
  const trimmed = raw.trim();
  if (trimmed === '' || trimmed.toLowerCase() === 'null') return null;

  switch (field.type) {
    case 'boolean':
      return trimmed.toLowerCase() === 'true';
    case 'integer':
      return Number.isNaN(Number(trimmed)) ? trimmed : Math.round(Number(trimmed));
    case 'float':
      return Number.isNaN(Number(trimmed)) ? trimmed : Number(trimmed);
    case 'list':
      try {
        const parsed = JSON.parse(trimmed);
        return Array.isArray(parsed) ? parsed : [trimmed];
      } catch {
        return trimmed.split(',').map((s) => {
          const t = s.trim();
          const n = Number(t);
          return Number.isNaN(n) ? t : n;
        });
      }
    default:
      return trimmed;
  }
}

/** Format a field value for display in a text input. */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return JSON.stringify(value);
  return String(value);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const CollapsibleSection: React.FC<{
  title: string;
  comment: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  dirtyCount?: number;
}> = ({ title, comment, defaultOpen = false, children, dirtyCount }) => {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-white/10 bg-white/5">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-white/5"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-300">{title}</span>
            {dirtyCount !== undefined && dirtyCount > 0 && (
              <span className="bg-accent-cyan/20 text-accent-cyan rounded-full px-1.5 py-0.5 text-[9px] font-bold">
                {dirtyCount}
              </span>
            )}
          </div>
          {comment && !open && <p className="mt-0.5 truncate text-xs text-slate-500">{comment}</p>}
        </div>
        <ChevronDown
          size={16}
          className={`shrink-0 text-slate-500 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="space-y-3 border-t border-white/5 px-4 py-3">
          {comment && <p className="text-xs text-slate-500">{comment}</p>}
          {children}
        </div>
      )}
    </div>
  );
};

const FieldRow: React.FC<{
  field: ConfigField;
  currentValue: unknown;
  isDirty: boolean;
  onChange: (path: string, value: unknown) => void;
}> = ({ field, currentValue, isDirty, onChange }) => {
  const displayValue = currentValue ?? field.value;

  if (field.type === 'boolean') {
    return (
      <div
        className={`rounded-lg px-3 py-1 ${isDirty ? 'bg-accent-cyan/5 ring-accent-cyan/20 ring-1' : ''}`}
      >
        <AppleSwitch
          checked={displayValue === true}
          onChange={(v) => onChange(field.path, v)}
          label={field.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
          description={field.comment}
          size="sm"
        />
      </div>
    );
  }

  const inputType = field.type === 'integer' || field.type === 'float' ? 'number' : 'text';
  const step = field.type === 'float' ? '0.01' : undefined;

  return (
    <div
      className={`rounded-lg px-3 py-2 ${isDirty ? 'bg-accent-cyan/5 ring-accent-cyan/20 ring-1' : ''}`}
    >
      <label className="mb-1 block text-xs font-medium text-slate-400">
        {field.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
      </label>
      <input
        type={inputType}
        step={step}
        value={formatValue(displayValue)}
        placeholder={field.value === null ? 'null' : ''}
        onChange={(e) => {
          const parsed = parseFieldValue(e.target.value, field);
          onChange(field.path, parsed);
        }}
        className="focus:border-accent-cyan/40 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-1.5 font-mono text-sm text-white placeholder:text-slate-600 focus:outline-none"
      />
      {field.comment && <p className="mt-1 text-xs leading-snug text-slate-500">{field.comment}</p>}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export const ServerConfigEditor: React.FC<ServerConfigEditorProps> = ({
  pendingUpdates,
  onFieldChange,
}) => {
  const [configTree, setConfigTree] = useState<ServerConfigTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const tree = await apiClient.getServerConfig();
      setConfigTree(tree);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load server config';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  // Filter sections/fields by search query
  const filteredSections = useMemo(() => {
    if (!configTree) return [];
    const q = searchQuery.toLowerCase().trim();
    if (!q) return configTree.sections;

    return configTree.sections
      .map((section) => {
        const sectionMatch =
          section.key.toLowerCase().includes(q) ||
          section.title.toLowerCase().includes(q) ||
          section.comment.toLowerCase().includes(q);

        const filteredFields = section.fields.filter(
          (f) =>
            sectionMatch ||
            f.key.toLowerCase().includes(q) ||
            f.comment.toLowerCase().includes(q) ||
            formatValue(f.value).toLowerCase().includes(q),
        );

        const filteredSubs = section.subsections
          .map((sub) => {
            const subMatch =
              sectionMatch ||
              sub.key.toLowerCase().includes(q) ||
              sub.title.toLowerCase().includes(q);
            const subFields = sub.fields.filter(
              (f) =>
                subMatch ||
                f.key.toLowerCase().includes(q) ||
                f.comment.toLowerCase().includes(q) ||
                formatValue(f.value).toLowerCase().includes(q),
            );
            return subFields.length > 0 ? { ...sub, fields: subFields } : null;
          })
          .filter(Boolean) as ConfigSubsection[];

        if (filteredFields.length > 0 || filteredSubs.length > 0) {
          return { ...section, fields: filteredFields, subsections: filteredSubs };
        }
        return null;
      })
      .filter(Boolean) as ConfigSection[];
  }, [configTree, searchQuery]);

  // Count dirty fields per section
  const dirtyCountForSection = useCallback(
    (section: ConfigSection): number => {
      let count = 0;
      for (const f of section.fields) {
        if (f.path in pendingUpdates) count++;
      }
      for (const sub of section.subsections) {
        for (const f of sub.fields) {
          if (f.path in pendingUpdates) count++;
        }
      }
      return count;
    },
    [pendingUpdates],
  );

  // ── Loading state ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-slate-500">
        <Loader2 size={20} className="mr-2 animate-spin" />
        Loading server configuration…
      </div>
    );
  }

  // ── Error state ──
  if (error) {
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 p-4">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-red-400" />
          <div>
            <p className="text-sm font-medium text-red-300">Could not load server config</p>
            <p className="mt-1 text-xs text-red-400/80">{error}</p>
          </div>
        </div>
        <button
          onClick={fetchConfig}
          className="flex items-center gap-2 text-xs text-slate-400 transition-colors hover:text-white"
        >
          <RefreshCw size={12} /> Retry
        </button>
      </div>
    );
  }

  // ── Empty state ──
  if (!configTree || configTree.sections.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">No configuration sections found.</p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search bar */}
      <div className="relative">
        <Search size={14} className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Filter settings…"
          className="focus:border-accent-cyan/40 w-full rounded-lg border border-white/10 bg-black/20 py-2 pr-3 pl-8 text-sm text-white placeholder:text-slate-600 focus:outline-none"
        />
      </div>

      {filteredSections.length === 0 && (
        <p className="py-6 text-center text-sm text-slate-500">
          No settings match &ldquo;{searchQuery}&rdquo;
        </p>
      )}

      {/* Sections */}
      {filteredSections.map((section) => (
        <CollapsibleSection
          key={section.key}
          title={section.title}
          comment={section.comment}
          defaultOpen={!!searchQuery}
          dirtyCount={dirtyCountForSection(section)}
        >
          {section.fields.map((field) => (
            <FieldRow
              key={field.path}
              field={field}
              currentValue={pendingUpdates[field.path] ?? field.value}
              isDirty={field.path in pendingUpdates}
              onChange={onFieldChange}
            />
          ))}

          {section.subsections.map((sub) => (
            <div key={sub.key} className="mt-3 space-y-3">
              <div className="flex items-center gap-2">
                <div className="h-px flex-1 bg-white/5" />
                <span className="text-[10px] font-bold tracking-wider text-slate-500 uppercase">
                  {sub.title}
                </span>
                <div className="h-px flex-1 bg-white/5" />
              </div>
              {sub.comment && <p className="text-xs text-slate-500">{sub.comment}</p>}
              {sub.fields.map((field) => (
                <FieldRow
                  key={field.path}
                  field={field}
                  currentValue={pendingUpdates[field.path] ?? field.value}
                  isDirty={field.path in pendingUpdates}
                  onChange={onFieldChange}
                />
              ))}
            </div>
          ))}
        </CollapsibleSection>
      ))}
    </div>
  );
};
