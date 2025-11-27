#!/usr/bin/env bash
# Start the TranscriptionSuite orchestrator
#
# This launches the orchestrator in tray mode (default).
# From the system tray you can:
# - Start long-form recording (left click)
# - Transcribe static file (right click menu)
# - Start Audio Notebook webapp (right click menu)
# - Quit
#
# Usage:
#   ./dev.sh              - Start orchestrator (tray mode)
#   ./dev.sh --frontend   - Also start the Audio Notebook frontend

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Parse arguments
WITH_FRONTEND=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --frontend)
            WITH_FRONTEND=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./dev.sh [--frontend]"
            exit 1
            ;;
    esac
done

# Check core venv exists
if [ ! -d "$CORE_DIR/.venv" ]; then
    echo "❌ Core venv not found at $CORE_DIR/.venv"
    echo "   Run 'cd $CORE_DIR && uv sync' first"
    exit 1
fi

echo "🚀 Starting TranscriptionSuite..."
echo ""

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    if [[ "$WITH_FRONTEND" == true ]]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    # Orchestrator handles its own cleanup
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start orchestrator in tray mode
cd "$CORE_DIR"

if [[ "$WITH_FRONTEND" == true ]]; then
    # Also start the frontend for development
    echo "🎨 Starting Audio Notebook frontend on http://localhost:1420..."
    cd "$SCRIPT_DIR"
    
    if [ ! -d "node_modules" ]; then
        echo "📥 Installing frontend dependencies..."
        npm install
    fi
    
    npm run dev &
    FRONTEND_PID=$!
    sleep 2
    
    cd "$CORE_DIR"
    echo ""
fi

echo "🔧 Starting orchestrator (tray mode)..."
echo ""
echo "═══════════════════════════════════════════════════"
echo "  TranscriptionSuite"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Look for the system tray icon (green = ready)"
echo ""
echo "  From the tray menu you can:"
echo "    • Left click  → Start long-form recording"
echo "    • Right click → Menu with more options"
echo ""
if [[ "$WITH_FRONTEND" == true ]]; then
echo "  Audio Notebook frontend: http://localhost:1420"
echo ""
fi
echo "  Press Ctrl+C to stop"
echo "═══════════════════════════════════════════════════"
echo ""

# Run orchestrator (this blocks until quit)
exec .venv/bin/python SCRIPT/orchestrator.py
