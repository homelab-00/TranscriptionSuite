import type { FallbackProps } from 'react-error-boundary';

export function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md rounded-2xl border border-red-500/20 bg-red-500/5 p-8 text-center">
        <h2 className="text-lg font-semibold text-red-400">Something went wrong</h2>
        <pre className="mt-3 max-h-40 overflow-auto text-left text-xs whitespace-pre-wrap text-slate-400">
          {error instanceof Error ? error.message : String(error)}
        </pre>
        <button
          onClick={resetErrorBoundary}
          className="mt-6 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
