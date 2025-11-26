#!/usr/bin/env bash
# Start the Transcription Viewer application in development mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Starting Transcription Viewer..."
echo ""

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start backend
echo "📦 Starting FastAPI backend on http://localhost:8000..."
cd "$SCRIPT_DIR/backend"

# Ensure venv exists and dependencies are installed
if [ ! -d ".venv" ]; then
    echo "📥 Creating backend virtual environment..."
    uv venv
fi
echo "📥 Syncing backend dependencies..."
uv sync

uv run uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Check backend health
if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✅ Backend ready!"
else
    echo "❌ Backend failed to start"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

# Start frontend
echo "🎨 Starting Vite frontend on http://localhost:1420..."
cd "$SCRIPT_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Transcription Viewer Development Server"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Frontend: http://localhost:1420"
echo "  Backend:  http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop all servers"
echo "═══════════════════════════════════════════════════"
echo ""

# Wait for either process to exit
wait
