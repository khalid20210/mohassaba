# 🚀 دليل النشر الكامل — jenanbiz.com

**المنصة:** Jenan Biz  
**الدومين:** https://jenanbiz.com  
**الخادم الموصى به:** Ubuntu 22.04 LTS  
**الوقت المتوقع:** 30-60 دقيقة

---

## 📋 ملخص خطوات النشر

```
1. استئجار خادم (VPS)
2. توجيه DNS لـ jenanbiz.com → IP الخادم
3. تسجيل الدخول للخادم
4. تشغيل سكريبت النشر setup.sh
5. التحقق من عمل الموقع
6. إضافة Google OAuth (اختياري)
```

---

## 1️⃣ متطلبات الخادم (VPS)

### مواصفات موصى بها (المرحلة الأولى: 500 منشأة)
| المورد | الحد الأدنى | الموصى به |
|--------|------------|-----------|
| CPU | 2 cores | 4 cores |
| RAM | 2 GB | 4-8 GB |
| Storage | 20 GB SSD | 50 GB SSD |
| Network | 1 Gbps | 1 Gbps |
| OS | Ubuntu 22.04 | Ubuntu 22.04 LTS |

### مزودو خدمة موصوف
| المزود | الخطة | السعر/شهر | المنطقة |
|--------|-------|-----------|---------|
| **DigitalOcean** | Basic 4GB | $24 | Frankfurt |
| **Hetzner** | CX31 | €12 | Helsinki |
| **Linode (Akamai)** | Shared 4GB | $24 | Frankfurt |
| **Vultr** | High Frequency 4GB | $24 | Frankfurt |

> **تلميح**: إن كان جمهورك في السعودية، اختر أقرب منطقة (Frankfurt أو Singapore).

---

## 2️⃣ إعداد DNS لـ jenanbiz.com

سجّل دخولاً لمزود الدومين وأضف السجلات التالية:

```
النوع   الاسم              القيمة               TTL
A       @                  <IP_الخادم>          300
A       www               <IP_الخادم>          300
```

### التحقق من DNS (بعد 5-30 دقيقة)
```bash
nslookup jenanbiz.com
# أو
dig jenanbiz.com A
```

> ⚠️ **مهم**: يجب أن يشير DNS لـ IP الخادم **قبل** تشغيل سكريبت SSL.

---

## 3️⃣ تشغيل سكريبت النشر التلقائي

### الاتصال بالخادم
```bash
ssh root@<IP_الخادم>
```

### تشغيل سكريبت النشر
```bash
# تحميل السكريبت
curl -fsSL https://raw.githubusercontent.com/khalid20210/mohassaba/master/deploy/setup.sh -o setup.sh

# تشغيله (يستغرق 5-15 دقيقة)
bash setup.sh
```

**ما يفعله السكريبت تلقائياً:**
- ✅ تثبيت Python, Nginx, Certbot, Fail2ban, UFW
- ✅ إنشاء مستخدم `jenanbiz` المعزول
- ✅ تحميل الكود من GitHub
- ✅ إنشاء virtual environment وتثبيت المتطلبات
- ✅ توليد SECRET_KEY عشوائي قوي
- ✅ إعداد Nginx كـ Reverse Proxy
- ✅ استخراج شهادة SSL من Let's Encrypt مجاناً
- ✅ إنشاء systemd service (تشغيل تلقائي عند إعادة التشغيل)
- ✅ إعداد Firewall (SSH + HTTP + HTTPS فقط)
- ✅ فحص صحة التطبيق

---

## 4️⃣ إعداد متغيرات البيئة

```bash
# تعديل ملف البيئة
nano /opt/jenanbiz/.env
```

**القيم الإجبارية:**
```ini
SECRET_KEY=<تم توليده تلقائياً بواسطة السكريبت>
PUBLIC_BASE_URL=https://jenanbiz.com
PLATFORM_NAME=Jenan Biz
```

**قيم اختيارية مهمة:**
```ini
# Google OAuth
GOOGLE_OAUTH_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=xxxxx

# Microsoft OAuth
MICROSOFT_OAUTH_CLIENT_ID=xxxxx
MICROSOFT_OAUTH_CLIENT_SECRET=xxxxx
```

---

## 5️⃣ إعداد Google OAuth (اختياري)

### خطوات الإعداد في Google Cloud Console
1. اذهب إلى [console.cloud.google.com](https://console.cloud.google.com)
2. أنشئ مشروعاً جديداً: `Jenan Biz`
3. فعّل **Google+ API** أو **Google Identity**
4. اذهب إلى **APIs & Services → Credentials**
5. اضغط **Create Credentials → OAuth 2.0 Client ID**
6. اختر **Web Application**
7. أضف:
   - **Authorized redirect URIs**: `https://jenanbiz.com/auth/social/google/callback`
8. انسخ **Client ID** و **Client Secret** في `/opt/jenanbiz/.env`
9. أعد تشغيل الخدمة: `systemctl restart jenanbiz`

---

## 6️⃣ شهادة SSL التفصيلية

### الحصول على الشهادة (تلقائي عبر setup.sh)
```bash
certbot --nginx \
    --email admin@jenanbiz.com \
    --agree-tos \
    --non-interactive \
    --domains jenanbiz.com,www.jenanbiz.com \
    --redirect
```

### التحقق من الشهادة
```bash
certbot certificates
# أو
openssl s_client -connect jenanbiz.com:443 -servername jenanbiz.com < /dev/null 2>/dev/null | openssl x509 -noout -dates
```

### التجديد التلقائي
الشهادة تُجدَّد تلقائياً (كل يوم اثنين 3 صباحاً).
```bash
# اختبار التجديد
certbot renew --dry-run
```

---

## 7️⃣ أوامر الإدارة اليومية

### إدارة الخدمة
```bash
systemctl status jenanbiz      # حالة الخدمة
systemctl restart jenanbiz     # إعادة تشغيل
systemctl stop jenanbiz        # إيقاف
journalctl -u jenanbiz -f      # سجلات مباشرة
journalctl -u jenanbiz -n 100  # آخر 100 سطر
```

### فحص الصحة
```bash
curl https://jenanbiz.com/healthz
curl https://jenanbiz.com/readyz
```

### النسخ الاحتياطي اليدوي
```bash
cp /opt/jenanbiz/database/accounting.db \
   "/opt/jenanbiz/backups/manual_$(date +%Y%m%d_%H%M%S).db"
```

### نسخ احتياطي تلقائي يومي
```bash
# أضف لـ crontab:
crontab -e
# أضف السطر:
0 2 * * * cp /opt/jenanbiz/database/accounting.db "/opt/jenanbiz/backups/auto_$(date +\%Y\%m\%d).db" && find /opt/jenanbiz/backups -name "auto_*.db" -mtime +30 -delete
```

### تحديث التطبيق
```bash
bash /opt/jenanbiz/deploy/update.sh
```

### إدارة Nginx
```bash
nginx -t                       # فحص الإعداد
systemctl reload nginx         # تطبيق التغييرات بلا انقطاع
tail -f /var/log/nginx/jenanbiz_access.log   # سجلات الوصول
tail -f /var/log/nginx/jenanbiz_error.log    # سجلات الأخطاء
```

---

## 8️⃣ مراقبة الموقع (Uptime Monitoring)

### UptimeRobot (مجاني)
1. سجّل على [uptimerobot.com](https://uptimerobot.com) (مجاني)
2. أضف Monitor جديد:
   - **النوع**: HTTP(S)
   - **URL**: `https://jenanbiz.com/healthz`
   - **التكرار**: كل دقيقة
   - **التنبيه**: بريدك الإلكتروني
3. ستحصل على تنبيه فوري عند أي انقطاع

---

## 9️⃣ أمان إضافي (موصى به)

### Fail2ban (تلقائي في setup.sh)
```bash
# فحص الحالة
fail2ban-client status
fail2ban-client status sshd
```

### فحص درجة الأمان SSL
بعد تثبيت الشهادة، اختبر:
- [ssllabs.com/ssltest](https://www.ssllabs.com/ssltest/analyze.html?d=jenanbiz.com) — يجب أن يكون **A أو A+**

### فحص Security Headers
- [securityheaders.com](https://securityheaders.com/?q=jenanbiz.com) — يجب أن يكون **A**

---

## 🔧 حل المشاكل الشائعة

### ❌ "Connection refused" على المنفذ 5001
```bash
journalctl -u jenanbiz -n 50   # فحص سبب الفشل
systemctl restart jenanbiz
```

### ❌ شهادة SSL فشلت
```bash
# تأكد من DNS أولاً
dig jenanbiz.com A             # يجب أن يعطي IP خادمك

# إعادة المحاولة يدوياً
certbot --nginx -d jenanbiz.com -d www.jenanbiz.com
```

### ❌ Nginx يعطي 502 Bad Gateway
```bash
systemctl status jenanbiz      # هل التطبيق يعمل؟
curl http://127.0.0.1:5001/healthz   # هل يستجيب محلياً؟
```

### ❌ صفحة بطيئة
```bash
# زد عدد الـ threads في /opt/jenanbiz/.env
WAITRESS_THREADS=32
systemctl restart jenanbiz
```

---

## 📊 مؤشرات الأداء المتوقعة

| المقياس | الهدف |
|---------|-------|
| زمن استجابة /healthz | < 50ms |
| زمن تحميل الصفحة | < 500ms |
| معدل الأخطاء | < 0.1% |
| SSL درجة | A+ |
| Uptime | 99.5%+ |

---

## 📞 معلومات الدعم

| الخدمة | الرابط |
|--------|--------|
| حالة Let's Encrypt | https://letsencrypt.status.io |
| توثيق Nginx | https://nginx.org/en/docs |
| حالة GitHub | https://www.githubstatus.com |

---

**الملف الأخير: deploy/DEPLOY_GUIDE.md**  
**الإصدار: 1.0 | Jenan Biz Platform**
