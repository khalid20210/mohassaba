#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  deploy/update.sh — سكريبت التحديث (للتشغيل عند كل إصدار جديد)
#  الاستخدام: sudo bash /opt/jenanbiz/deploy/update.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[✅ OK]${NC} $*"; }

APP_DIR="/opt/jenanbiz"
APP_USER="jenanbiz"
VENV="${APP_DIR}/.venv"
BRANCH="master"
BACKUP_DIR="${APP_DIR}/backups"

# نسخ احتياطي قبل التحديث
info "نسخ احتياطي للقاعدة..."
DB_FILE=$(find "${APP_DIR}/database" -name "*.db" | head -1)
if [[ -n "${DB_FILE}" ]]; then
    cp "${DB_FILE}" "${BACKUP_DIR}/pre_update_$(date +%Y%m%d_%H%M%S).db"
    success "نسخة احتياطية: ${BACKUP_DIR}"
fi

# جلب آخر الكود
info "تحديث الكود..."
sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch origin
sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"

# تحديث المتطلبات
info "تحديث المتطلبات..."
sudo -u "${APP_USER}" "${VENV}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

# ترقية DB
info "تطبيق ترقيات قاعدة البيانات..."
cd "${APP_DIR}"
sudo -u "${APP_USER}" "${VENV}/bin/python" -c "
from modules import create_app; app = create_app()
with app.app_context(): print('Migrations OK')
"

# إعادة تشغيل الخدمة
info "إعادة تشغيل الخدمة..."
systemctl restart jenanbiz
sleep 2

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:5001/healthz" || echo "000")
echo -e "\n${GREEN}${BOLD}═══════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✅ التحديث اكتمل — HTTP: ${HTTP_STATUS}${NC}"
echo -e "${GREEN}${BOLD}═══════════════════════════════════════${NC}\n"
