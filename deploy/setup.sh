#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  deploy/setup.sh — سكريبت النشر التلقائي الكامل
#  Jenan Biz Platform → jenanbiz.com
#  الهدف: Ubuntu 22.04 LTS / Debian 12
#  التشغيل: sudo bash setup.sh
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── ألوان للمخرجات ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[✅ OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[⚠️  WARN]${NC} $*"; }
error()   { echo -e "${RED}[❌ ERROR]${NC} $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${YELLOW}━━━ $* ━━━${NC}"; }

# ── متغيرات النشر ─────────────────────────────────────────────────────────
DOMAIN="jenanbiz.com"
APP_DIR="/opt/jenanbiz"
APP_USER="jenanbiz"
REPO_URL="https://github.com/khalid20210/mohassaba.git"
BRANCH="master"
PYTHON_MIN="3.11"
NGINX_SITE="/etc/nginx/sites-available/${DOMAIN}"
CERTBOT_EMAIL="admin@jenanbiz.com"   # ← غيّره لبريد حقيقي

# ════════════════════════════════════════════════════════════════════════════
step "1 — التحقق من المتطلبات"
# ════════════════════════════════════════════════════════════════════════════
[[ $(id -u) -eq 0 ]] || error "شغّل السكريبت بصلاحيات root: sudo bash setup.sh"
[[ -f /etc/debian_version ]] || error "هذا السكريبت مصمم لـ Ubuntu/Debian فقط"
info "Ubuntu/Debian مكتشف ✓"

# ════════════════════════════════════════════════════════════════════════════
step "2 — تثبيت الحزم الأساسية"
# ════════════════════════════════════════════════════════════════════════════
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    nginx certbot python3-certbot-nginx \
    git curl wget ufw fail2ban \
    build-essential libssl-dev libffi-dev \
    sqlite3 libsqlite3-dev
success "الحزم الأساسية مثبتة"

# ════════════════════════════════════════════════════════════════════════════
step "3 — إنشاء مستخدم النظام jenanbiz"
# ════════════════════════════════════════════════════════════════════════════
if ! id "${APP_USER}" &>/dev/null; then
    useradd --system --shell /bin/false --home "${APP_DIR}" --create-home "${APP_USER}"
    success "المستخدم ${APP_USER} أُنشئ"
else
    info "المستخدم ${APP_USER} موجود مسبقاً"
fi

# ════════════════════════════════════════════════════════════════════════════
step "4 — تحميل / تحديث الكود"
# ════════════════════════════════════════════════════════════════════════════
if [[ -d "${APP_DIR}/.git" ]]; then
    info "تحديث الكود من GitHub..."
    sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch origin
    sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
else
    info "استنساخ المستودع..."
    rm -rf "${APP_DIR}"
    git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${APP_DIR}"
    chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
fi
success "الكود محدّث"

# ════════════════════════════════════════════════════════════════════════════
step "5 — إنشاء البيئة الافتراضية وتثبيت المتطلبات"
# ════════════════════════════════════════════════════════════════════════════
VENV="${APP_DIR}/.venv"
if [[ ! -d "${VENV}" ]]; then
    sudo -u "${APP_USER}" python3 -m venv "${VENV}"
fi
sudo -u "${APP_USER}" "${VENV}/bin/pip" install --quiet --upgrade pip
sudo -u "${APP_USER}" "${VENV}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
success "المتطلبات مثبتة"

# ════════════════════════════════════════════════════════════════════════════
step "6 — إعداد مجلدات البيانات"
# ════════════════════════════════════════════════════════════════════════════
for dir in database backups exports instance/sessions logs; do
    mkdir -p "${APP_DIR}/${dir}"
done
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/database" \
    "${APP_DIR}/backups" "${APP_DIR}/exports" \
    "${APP_DIR}/instance" "${APP_DIR}/logs"
chmod 750 "${APP_DIR}/database" "${APP_DIR}/backups"
success "المجلدات جاهزة"

# ════════════════════════════════════════════════════════════════════════════
step "7 — إعداد ملف البيئة (.env)"
# ════════════════════════════════════════════════════════════════════════════
ENV_FILE="${APP_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${APP_DIR}/deploy/env.production" "${ENV_FILE}"

    # توليد SECRET_KEY تلقائياً
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(64))")
    sed -i "s/REPLACE_WITH_STRONG_RANDOM_KEY_64_CHARS_MIN/${SECRET}/" "${ENV_FILE}"

    chown "${APP_USER}:${APP_USER}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    warn "تم إنشاء .env — راجع الملف وأضف إعداداتك: ${ENV_FILE}"
else
    info ".env موجود مسبقاً — لم يُعدَّل"
fi

# ════════════════════════════════════════════════════════════════════════════
step "8 — تشغيل ترقيات قاعدة البيانات"
# ════════════════════════════════════════════════════════════════════════════
cd "${APP_DIR}"
sudo -u "${APP_USER}" "${VENV}/bin/python" -c "
from modules import create_app
app = create_app()
with app.app_context():
    print('DB migrations applied OK')
" && success "قاعدة البيانات محدّثة" || warn "تحقق من قاعدة البيانات يدوياً"

# ════════════════════════════════════════════════════════════════════════════
step "9 — إعداد Nginx"
# ════════════════════════════════════════════════════════════════════════════

# نسخ proxy params
cp "${APP_DIR}/deploy/nginx/proxy_params_jenanbiz" /etc/nginx/proxy_params_jenanbiz

# صفحة 429
cat > /var/www/html/429.html << 'EOF'
<!DOCTYPE html><html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><title>طلبات كثيرة</title>
<style>body{font-family:Arial,sans-serif;text-align:center;padding:60px;background:#0f172a;color:#e2e8f0}
h1{font-size:3rem;color:#f87171}p{color:#94a3b8;font-size:1.1rem}</style></head>
<body><h1>429</h1><p>طلبات كثيرة جداً — يرجى الانتظار قليلاً والمحاولة مجدداً.</p></body></html>
EOF

# نسخ إعداد nginx
cp "${APP_DIR}/deploy/nginx/jenanbiz.conf" "${NGINX_SITE}"

# تفعيل الموقع
ln -sf "${NGINX_SITE}" /etc/nginx/sites-enabled/

# إزالة الموقع الافتراضي
rm -f /etc/nginx/sites-enabled/default

# التحقق من صحة الإعداد
nginx -t && success "Nginx صالح" || error "خطأ في إعداد Nginx"
systemctl reload nginx
success "Nginx مُعدّ ومُفعَّل"

# ════════════════════════════════════════════════════════════════════════════
step "10 — استخراج شهادة SSL (Let's Encrypt)"
# ════════════════════════════════════════════════════════════════════════════
# تأكد من أن DNS يشير للخادم قبل هذه الخطوة!
if [[ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]]; then
    info "طلب شهادة SSL لـ ${DOMAIN}..."
    certbot --nginx \
        --non-interactive \
        --agree-tos \
        --email "${CERTBOT_EMAIL}" \
        --domains "${DOMAIN},www.${DOMAIN}" \
        --redirect \
        --staple-ocsp \
        --hsts \
        --must-staple
    success "شهادة SSL مثبتة"
else
    info "شهادة SSL موجودة — تجديد إن احتجت: certbot renew"
fi

# تجديد تلقائي (Cron Job)
if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (crontab -l 2>/dev/null; echo "0 3 * * 1 certbot renew --quiet --post-hook 'systemctl reload nginx'") | crontab -
    success "تجديد SSL تلقائي مُجدوَل (كل اثنين الساعة 3 صباحاً)"
fi

# ════════════════════════════════════════════════════════════════════════════
step "11 — تثبيت Systemd Service"
# ════════════════════════════════════════════════════════════════════════════
cp "${APP_DIR}/deploy/systemd/jenanbiz.service" /etc/systemd/system/jenanbiz.service
systemctl daemon-reload
systemctl enable jenanbiz
systemctl restart jenanbiz
sleep 3

if systemctl is-active --quiet jenanbiz; then
    success "خدمة jenanbiz تعمل ✓"
else
    error "فشل تشغيل الخدمة — تحقق: journalctl -u jenanbiz -n 50"
fi

# ════════════════════════════════════════════════════════════════════════════
step "12 — إعداد Firewall (UFW)"
# ════════════════════════════════════════════════════════════════════════════
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
success "Firewall مُفعَّل (SSH + HTTP + HTTPS فقط)"

# ════════════════════════════════════════════════════════════════════════════
step "13 — اختبار صحة التطبيق"
# ════════════════════════════════════════════════════════════════════════════
sleep 2
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://${DOMAIN}/healthz" 2>/dev/null || echo "000")
if [[ "${HTTP_STATUS}" == "200" ]]; then
    success "التطبيق يعمل على https://${DOMAIN}/healthz → HTTP ${HTTP_STATUS}"
else
    warn "صحة التطبيق: HTTP ${HTTP_STATUS} — تحقق يدوياً: curl https://${DOMAIN}/healthz"
fi

# ════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  ✅ تم النشر بنجاح! Jenan Biz → https://${DOMAIN}${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  📋 أوامر مفيدة:"
echo -e "  ${CYAN}systemctl status jenanbiz${NC}         — حالة الخدمة"
echo -e "  ${CYAN}journalctl -u jenanbiz -f${NC}         — سجلات مباشرة"
echo -e "  ${CYAN}systemctl restart jenanbiz${NC}        — إعادة تشغيل"
echo -e "  ${CYAN}nginx -t && systemctl reload nginx${NC} — تطبيق تغييرات nginx"
echo -e "  ${CYAN}curl https://${DOMAIN}/healthz${NC}   — فحص الصحة"
echo -e "  ${CYAN}certbot renew --dry-run${NC}           — اختبار تجديد SSL"
echo ""
echo -e "  ⚠️  تذكّر: عدّل ${CYAN}/opt/jenanbiz/.env${NC} وأضف:"
echo -e "    - GOOGLE_OAUTH_CLIENT_ID / SECRET"
echo -e "    - CERTBOT_EMAIL الصحيح"
echo ""
