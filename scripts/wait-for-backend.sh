#!/usr/bin/env bash
# Wait for backend to be ready before proceeding

BACKEND_URL="${1:-http://localhost:8000}"
MAX_WAIT="${2:-30}"
WAIT_INTERVAL=1

echo "Waiting for backend at $BACKEND_URL..."

elapsed=0
while [ $elapsed -lt $MAX_WAIT ]; do
    if curl -sf "$BACKEND_URL/health" > /dev/null 2>&1; then
        echo "✅ Backend is ready!"
        exit 0
    fi
    
    echo "⏳ Waiting... ($elapsed/$MAX_WAIT seconds)"
    sleep $WAIT_INTERVAL
    elapsed=$((elapsed + WAIT_INTERVAL))
done

echo "❌ Backend did not become ready within $MAX_WAIT seconds"
exit 1
