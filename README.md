# 🌿 محصولي ويب — دليل النشر على Render

## 🚀 خطوات النشر على Render (مجاني)

### الخطوة 1: رفع الكود على GitHub
1. اذهب إلى **github.com** وأنشئ حساباً مجانياً
2. أنشئ **Repository** جديد باسم `mahsoli-web`
3. ارفع جميع ملفات هذا المجلد

### الخطوة 2: إنشاء الخدمة على Render
1. اذهب إلى **render.com** وأنشئ حساباً مجانياً
2. اضغط **New → Web Service**
3. اربطه بـ GitHub Repository الذي أنشأته
4. اضبط هذه الإعدادات:
   - **Name**: `mahsoli-web`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 1 --bind 0.0.0.0:$PORT --timeout 120`
5. اضغط **Create Web Service**

### الخطوة 3: إضافة Disk (للبيانات)
1. في صفحة الخدمة، اذهب إلى **Disks**
2. اضغط **Add Disk**
3. اضبط:
   - **Name**: `mahsoli-data`
   - **Mount Path**: `/opt/render/project/src/mahsoli_data`
   - **Size**: `1 GB`

### الخطوة 4: تشغيل!
- بعد دقيقتين سيعطيك Render رابطاً مثل: `https://mahsoli-web.onrender.com`
- افتحه من أي هاتف أو كمبيوتر! 🎉

---

## 📱 الميزات
- ✅ داشبورد شامل مع إحصائيات
- ✅ إدخال مبيعات جديدة
- ✅ إدارة المشترين والفواتير
- ✅ تقارير وإكسل
- ✅ نسخ احتياطي تلقائي
- ✅ واتساب مباشر
- ✅ يعمل على الموبايل 100%

## 🔧 التشغيل المحلي
```bash
pip install -r requirements.txt
python app.py
```
ثم افتح: http://localhost:5000

## 📤 نقل بياناتك القديمة
انسخ ملف `mahsoli.db` من مجلد `mahsoli_data` في برنامجك القديم
وضعه في مجلد `mahsoli_data` في هذا المشروع قبل الرفع.
