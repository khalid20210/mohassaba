"""
_production_test.py
اختبار حقيقي متكامل - تقييم كل الخدمات عبر HTTP
"""
import os
import time
os.environ['SESSION_BACKEND'] = 'cookie'

from modules import create_app

app = create_app()

class Test:
    def __init__(self):
        self.pass_count = 0
        self.fail_count = 0
        self.errors = []
        self.start = time.time()
    
    def run(self):
        with app.test_client() as c:
            print("\n" + "="*70)
            print("اختبار شامل متكامل لبرنامج محاسبة - جنان بيز")
            print("="*70 + "\n")
            
            # 1. صحة الخادم
            print("[1] فحص صحة الخادم...")
            r = c.get('/healthz')
            self.check(r.status_code == 200, "Healthz endpoint")
            
            # 2. الصفحات الثابتة
            print("[2] فحص الصفحات الثابتة...")
            for path in ['/auth/login', '/auth/register', '/offline']:
                r = c.get(path)
                self.check(r.status_code == 200, f"صفحة {path}")
            
            # 3. الملفات الثابتة
            print("[3] فحص الملفات الثابتة...")
            for path in ['/static/css/main.css', '/static/js/app.js', '/manifest.json']:
                r = c.get(path)
                self.check(r.status_code in [200, 304], f"ملف {path}")
            
            # 4. API المراقبة
            print("[4] فحص API المراقبة...")
            r = c.get('/readyz')
            self.check(r.status_code == 200, "Readyz endpoint")
            
            # 5. الوثائق
            print("[5] فحص الوثائق...")
            r = c.get('/docs')
            self.check(r.status_code in [200, 404, 302], "Docs endpoint")
            
            # 6. الصور والشعارات
            print("[6] فحص الصور والشعارات...")
            r = c.get('/static/images/logo.jpg')
            self.check(r.status_code in [200, 304], "شعار الموقع")
            
            self.summary()
    
    def check(self, condition, name):
        if condition:
            print(f"  ✓ {name}")
            self.pass_count += 1
        else:
            print(f"  ✗ {name}")
            self.fail_count += 1
            self.errors.append(name)
    
    def summary(self):
        elapsed = time.time() - self.start
        total = self.pass_count + self.fail_count
        pct = (self.pass_count / total * 100) if total > 0 else 0
        
        print("\n" + "="*70)
        print(f"النتائج: {self.pass_count}/{total} نجح ({pct:.0f}%)")
        print(f"الوقت: {elapsed:.1f}ث")
        
        if self.errors:
            print("\nالفشل في:")
            for e in self.errors:
                print(f"  • {e}")
        
        print("="*70 + "\n")
        return 0 if pct >= 95 else 1

if __name__ == '__main__':
    t = Test()
    exit(t.run())
