#!/usr/bin/env bash

set -o errexit

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Applying database migrations..."
python manage.py migrate

echo "Creating evaluation data..."
python manage.py seed_evaluation_data

if [ -n "${DEMO_ADMIN_PASSWORD:-}" ]; then
    echo "Creating/updating demo admin..."

    python manage.py create_demo_admin \
        --username "${DEMO_ADMIN_USERNAME:-demo_admin}" \
        --email "${DEMO_ADMIN_EMAIL:-demo@example.com}" \
        --password "${DEMO_ADMIN_PASSWORD}"
else
    echo "DEMO_ADMIN_PASSWORD is not set; skipping demo admin creation."
fi

echo "Build completed successfully."
