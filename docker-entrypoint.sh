#!/usr/bin/env sh
set -eu

mkdir -p /app/data /app/data/uploads /app/data/logos /app/data/sessions

if [ ! -f /app/data/accounting_dev.db ]; then
  cp /app/database/accounting_dev.db /app/data/accounting_dev.db
fi

export FLASK_ENV=${FLASK_ENV:-production}
export HOST=${HOST:-0.0.0.0}
export PORT=${PORT:-5001}
export DB_PATH=${DB_PATH:-/app/data/accounting_dev.db}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/data/uploads}
export LOGO_FOLDER=${LOGO_FOLDER:-/app/data/logos}
export SESSION_FILE_DIR=${SESSION_FILE_DIR:-/app/data/sessions}

exec python run_production.py
