#!/usr/bin/env bash

set -o errexit

echo "Starting email queue processor..."

python manage.py process_email_queue \
    --loop \
    --interval "${EMAIL_QUEUE_INTERVAL:-30}" &

EMAIL_WORKER_PID=$!

cleanup() {
    echo "Stopping background email processor..."
    kill "$EMAIL_WORKER_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "Starting Gunicorn..."

gunicorn bookmyseat.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 1 \
    --timeout 120
