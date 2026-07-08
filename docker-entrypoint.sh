#!/usr/bin/env sh
set -eu

mkdir -p /app/data /app/data/uploads /app/data/logos /app/data/sessions

# نسخ قاعدة البيانات (إنتاجية أولاً)
if [ ! -f /app/data/accounting_prod.db ]; then
  if [ -f /app/database/accounting_prod.db ]; then
    cp /app/database/accounting_prod.db /app/data/accounting_prod.db
  else
    cp /app/database/accounting_dev.db   /app/data/accounting_prod.db
  fi
fi

# توليد SECRET_KEY آمن إن لم يكن محدداً (للحاويات السحابية)
if [ -z "${SECRET_KEY:-}" ]; then
  export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
fi

export FLASK_ENV=${FLASK_ENV:-production}
export HOST=${HOST:-0.0.0.0}
export PORT=${PORT:-5001}
export DB_PATH=${DB_PATH:-/app/data/accounting_prod.db}
export UPLOAD_FOLDER=${UPLOAD_FOLDER:-/app/data/uploads}
export LOGO_FOLDER=${LOGO_FOLDER:-/app/data/logos}
export SESSION_FILE_DIR=${SESSION_FILE_DIR:-/app/data/sessions}
export BEHIND_PROXY=${BEHIND_PROXY:-true}
export SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-false}

echo "Starting Jenan Biz | ENV=$FLASK_ENV | PORT=$PORT"
exec python run_production.py
