"""
═══════════════════════════════════════════════════════════════════════════
🔥 ملك الطابون - Backend المركزي (العقل) - النسخة المطورة - Flask Edition
═══════════════════════════════════════════════════════════════════════════

هذا هو الوسيط الآمن بين موقع العملاء وموقع العمال
تم إعادة كتابته لاستخدام Flask لضمان التوافقية القصوى.
يقوم الآن بخدمة ملفات Frontend مباشرة (Monolith Architecture).

المسؤوليات:
1. حماية مفتاح OpenAI API
2. التواصل مع الذكاء الاصطناعي (via Raw HTTP)
3. استقبال وتخزين الطلبات
4. توزيع البيانات للموقعين
5. مسح تلقائي للطلبات القديمة
6. ✅ دعم ثلاثة أنواع من الزبائن
7. ✅ WebSocket للإشعارات الفورية للعملاء
8. ✅ خدمة ملفات الموقعين (Customers & Staff)

═══════════════════════════════════════════════════════════════════════════
"""

from flask import Flask, request, jsonify, make_response, send_from_directory, redirect
from flask_cors import CORS
from flask_sock import Sock
from datetime import datetime, timedelta
import os
import json
import re
import threading
import time
import requests
from dotenv import load_dotenv
import pytz

from pymongo import MongoClient
from pymongo.server_api import ServerApi

# تحميل متغيرات البيئة
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# 💾 قاعدة بيانات MongoDB - التخزين الدائم
# ═══════════════════════════════════════════════════════════════════════════

MONGODB_URL = "mongodb+srv://tech40210_db_user:tnyIoqe5elfdf29O@cluster0.pqho6kg.mongodb.net/?appName=Cluster0"
mongo_client = None
db_customers = None
db_orders = None

if MONGODB_URL:
    try:
        mongo_client = MongoClient(MONGODB_URL, server_api=ServerApi('1'))
        # Send a ping to confirm a successful connection
        mongo_client.admin.command('ping')
        print("✅ Pinged your deployment. You successfully connected to MongoDB!")
        
        # Access database and collections
        database = mongo_client['king_of_taboon']
        db_customers = database['customers']
        db_orders = database['orders']
        print("✅ MongoDB Collections initialized")
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}")
else:
    print("⚠️ No MONGODB_URL provided")

def get_customer_data(fingerprint):
    """الحصول على بيانات زبون معين من MongoDB"""
    if db_customers is not None:
        try:
            return db_customers.find_one({'_id': fingerprint})
        except Exception as e:
            print(f"Error reading customer: {e}")
            return None
    return None

def save_customer_data(fingerprint, data):
    """حفظ بيانات زبون في MongoDB"""
    if db_customers:
        try:
            update_data = {
                **data,
                'lastVisit': datetime.now().isoformat()
            }
            # Upsert: Update if exists, Insert if not
            db_customers.update_one(
                {'_id': fingerprint},
                {
                    '$set': update_data,
                    '$inc': {'visitCount': 1}
                },
                upsert=True
            )
            print(f"💾 Customer {fingerprint} saved to MongoDB")
        except Exception as e:
            print(f"Error saving customer: {e}")

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 الإعدادات الحساسة
# ═══════════════════════════════════════════════════════════════════════════

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not OPENAI_API_KEY:
    print('⚠️  تحذير: مفتاح OpenAI غير مُعد! أضفه في متغيرات البيئة')

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 إنشاء التطبيق وإعداد المسارات
# ═══════════════════════════════════════════════════════════════════════════

# تحديد مسارات المجلدات الأمامية
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CUSTOMERS_DIR = os.path.join(BASE_DIR, '../frontend-customers')
STAFF_DIR = os.path.join(BASE_DIR, '../frontend-staff')

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# ═══════════════════════════════════════════════════════════════════════════
# 🌐 خدمة الملفات الثابتة (Frontend Serving)
# ═══════════════════════════════════════════════════════════════════════════

# 1. خدمة موقع العملاء (على الجذر /)
@app.route('/')
def serve_customers_index():
    return send_from_directory(CUSTOMERS_DIR, 'index.html')

@app.route('/<path:path>')
def serve_customers_static(path):
    # إذا كان الملف موجوداً في مجلد العملاء، قم بخدمته
    if os.path.exists(os.path.join(CUSTOMERS_DIR, path)):
        return send_from_directory(CUSTOMERS_DIR, path)
    return "Not Found", 404

# 2. خدمة موقع العمال (على /staff)
@app.route('/staff')
def redirect_staff_index():
    return redirect('/staff/')

@app.route('/staff/')
def serve_staff_index():
    return send_from_directory(STAFF_DIR, 'index.html')

@app.route('/staff/<path:path>')
def serve_staff_static(path):
    # إذا كان الملف موجوداً في مجلد العمال، قم بخدمته
    if os.path.exists(os.path.join(STAFF_DIR, path)):
        return send_from_directory(STAFF_DIR, path)
    return "Not Found", 404

# ═══════════════════════════════════════════════════════════════════════════
# 📦 قاعدة البيانات (MongoDB Wrapper)
# ═══════════════════════════════════════════════════════════════════════════

class Database:
    def __init__(self):
        # لم نعد نستخدم القائمة المحلية، بل نعتمد على MongoDB مباشرة
        pass

    @property
    def orders(self):
        """جلب جميع الطلبات من MongoDB كقائمة (للتوافق مع الكود القديم)"""
        if db_orders:
            try:
                # جلب آخر 100 طلب فقط للأداء، مرتبة تنازلياً
                cursor = db_orders.find().sort('id', -1).limit(100)
                return list(cursor)
            except Exception as e:
                print(f"Error fetching orders: {e}")
                return []
        return []

    @property
    def counter(self):
        """الحصول على آخر ID للطلبات"""
        if db_orders:
            try:
                last_order = db_orders.find_one(sort=[("id", -1)])
                if last_order:
                    return last_order['id']
            except:
                pass
        return 1000

    @counter.setter
    def counter(self, value):
        # لا نحتاج لتعيين العداد يدوياً لأننا نحسبه من القاعدة
        pass

    def add_order(self, order):
        """إضافة طلب جديد إلى MongoDB"""
        if db_orders:
            try:
                # استخدام _id كـ id الطلب للسهولة
                order['_id'] = order['id']
                db_orders.insert_one(order)
                print(f"💾 Order #{order['id']} saved to MongoDB")
            except Exception as e:
                print(f"Error adding order: {e}")

    def update_order(self, order_id, updates):
        """تحديث طلب في MongoDB"""
        if db_orders:
            try:
                db_orders.update_one(
                    {'id': order_id},
                    {'$set': updates}
                )
                print(f"💾 Order #{order_id} updated in MongoDB")
            except Exception as e:
                print(f"Error updating order: {e}")

db = Database()

# ═══════════════════════════════════════════════════════════════════════════
# 🔌 WebSocket Connection Manager
# ═══════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}  # {order_id: [ws, ...]}
        self.all_connections = []     # [ws, ...]
        self.lock = threading.Lock()
    
    def connect(self, ws, order_id=None):
        with self.lock:
            self.all_connections.append(ws)
            if order_id:
                if order_id not in self.active_connections:
                    self.active_connections[order_id] = []
                self.active_connections[order_id].append(ws)
                print(f"🔗 عميل متصل لمتابعة الطلب #{order_id}")
            else:
                print(f"🔗 عميل متصل (بدون طلب محدد)")

    def disconnect(self, ws, order_id=None):
        with self.lock:
            if ws in self.all_connections:
                self.all_connections.remove(ws)
            if order_id and order_id in self.active_connections:
                if ws in self.active_connections[order_id]:
                    self.active_connections[order_id].remove(ws)
                if not self.active_connections[order_id]:
                    del self.active_connections[order_id]
        print(f"🔌 عميل قطع الاتصال")

    def broadcast(self, message):
        with self.lock:
            msg_str = json.dumps(message)
            to_remove = []
            for ws in self.all_connections:
                try:
                    ws.send(msg_str)
                except:
                    to_remove.append(ws)
            for ws in to_remove:
                if ws in self.all_connections:
                    self.all_connections.remove(ws)
        
        if message.get('type') == 'order_ready':
            print(f"📢 تم بث إشعار جاهزية للجميع - الطلب #{message.get('orderId')}")

    def send_to_order(self, order_id, message):
        with self.lock:
            if order_id in self.active_connections:
                msg_str = json.dumps(message)
                to_remove = []
                for ws in self.active_connections[order_id]:
                    try:
                        ws.send(msg_str)
                        print(f"📤 تم إرسال إشعار للطلب #{order_id}")
                    except:
                        to_remove.append(ws)
                for ws in to_remove:
                    if ws in self.active_connections[order_id]:
                        self.active_connections[order_id].remove(ws)

manager = ConnectionManager()

# ═══════════════════════════════════════════════════════════════════════════
# 🤖 System Prompt
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """# وكيل طلبات مطعم ملك الطابون

## 🧠 الذاكرة الذكية
إذا وجدت بيانات محفوظة للزبون:
- استخدمها مباشرة بدون السؤال عنها مرة ثانية
- اذكر اسمه وقل "أهلاً [الاسم]!"
- إذا كان orderType محفوظ، اسأل: "زي العادة [داخل المحل/بالسيارة/توصيل]؟"
- إذا كانت السيارة محفوظة، قل: "السيارة [اللون] صح؟"

⚠️ مهم: اسأل فقط عن البيانات الناقصة!

## هويتك
أنت مساعد طلبات مطعم "ملك الطابون والمعجنات" في العيزرية. تستقبل طلبات الزبائن باللهجة الفلسطينية.

## معلومات المطعم
- الاسم: ملك الطابون
- العنوان: العيزرية - دوار وادي النار
- ساعات العمل: 8:00 صباحاً - 2:00 بعد منتصف الليل (يومياً)
- وقت التحضير: 7-10 دقيقة الوجبة دون وقت التوصيل
- التوصيل: متوفر للعيزرية والمناطق المجاورة
- الدفع: كاش أو فيزا داخل المحل فقط

## قواعد السلوك
1. تحدث بلهجة فلسطينية بسيطة وودودة
2. كن مختصراً - لا تكتب رسائل طويلة
3. لا تعرض القائمة كاملة - اعرض فقط خيارات الصنف المطلوب
4. استخدم إيموجي واحد أو اثنين فقط
5. لا تخترع أصناف غير موجودة ولا تغير الأسعار
6. لمن هو بالمحل او بالسيارة أطلب منه الاسم + الطلب.
7. قم بإخبار الزبون بالسعر مع طلب التأكيد
8. بمجرد التأكيد, أطلب منه إستلام الطلب بعد 7-10 دقائق, طلبات التوصيل تستغرق 10-20 دقيقة حسب الموقع والطلب
9. في حال طلب  "معجنات مناسبات" أخبره أن يتواصل معنا عبر الواتساب 0523668131

## خاص لطلبيات التوصيل
- الأسم الثنائي
- اطلب منه رقم الجوال (إجباري). 
- اخذ عنوان الموقع واسم البيت او مكان العمل. 
- اخبارهم ان التوصيل يكلف  10-20 شيكل حسب الموقع بأماكن العيزرية أو السواحرة.
- التوصيل لأماكن في العيزرية ب شيكل 15 والسواحرة ب 20 شيكل
- جمع تكلفة الطلب مع تكلفة التوصيل حسب المنطقة واخبار الزبون.

## ✅ نظام أنواع الزبائن الثلاثة - مهم جداً!

### المعلومات المطلوبة حسب نوع الزبون:

**1️⃣ زبون داخل المحل (dine_in):**
- الاسم
- الطلب
- فقط! لا حاجة لمزيد من التفاصيل

**2️⃣ زبون بالسيارة (car_pickup):**
- الاسم
- الطلب
- رقم الجوال (للتواصل لما يكون الطلب جاهز)
- لون السيارة أو نوعها (اختياري لتسهيل التعرف)

**3️⃣ زبون توصيل (delivery):**
- الاسم
- الطلب
- رقم الجوال (إجباري)
- العنوان بالتفصيل (عنوان المنطقة/أقرب نقطة معروفة)
- ملاحظات التوصيل (اختياري)

## تنسيق الطلب النهائي - مهم جداً!
عندما يؤكد الزبون طلبه، يجب أن تضيف في نهاية ردك هذا التنسيق بالضبط:

[ORDER_DATA]
{
  "customer": "اسم الزبون",
  "phone": "رقم الجوال أو فارغ",
  "items": "الأصناف المطلوبة",
  "total": المبلغ_رقم,
  "orderType": "dine_in أو car_pickup أو delivery",
  "location": "داخل المحل أو بالسيارة أو اسم المنطقة للتوصيل",
  "address": "العنوان التفصيلي للتوصيل فقط",
  "carInfo": "معلومات السيارة للزبون بالسيارة",
  "deliveryNotes": "ملاحظات التوصيل"
}
[/ORDER_DATA]

## القائمة الكاملة

### البيتزا أو معجنات الطابون
- بيتزا الطابون: 20 شيكل
- بيتزا بالجبنة البيضاء: 23 شيكل
- بيتزا تونا: 25 شيكل
- بيتزا ستيك دجاج: 30 شيكل
- بيتزا سلامي: 25 شيكل
- بيتزا مكس جبنة: 22 شيكل
- بيتزا مكسيكي حار: 30 شيكل
- بيتزا نقانق: 23 شيكل
- بيتزا عيمك خضار: 25 شيكل
- بيتزا عيمك ستيك: 35 شيكل
- بيتزا عيمك سلامي: 30 شيكل
- بيتزا عيمك مكسيكي: 35 شيكل
- بيتزا عيمك نقانق: 28 شيكل

### البيض
- بيض سادة: 8 شيكل
- بيض مع جبنة بيضاء: 15 شيكل
- بيض مع جبنة عيمك: 21 شيكل
- بيض مع جبنة موزاريلا: 14 شيكل
- بيض مع جبنة ونقانق: 17 شيكل
- بيض مع زيتون ودرة: 12 شيكل
- بيض مع سجق: 20 شيكل
- بيض مع سجق وجبنة: 22 شيكل
- بيض مع سجق وجبنة عيمك: 28 شيكل
- بيض مع سجق وجبنة ونقانق: 28 شيكل
- بيض مع عيمك ونقانق: 23 شيكل
- بيض مع لحمة بالجبنة: 25 شيكل
- بيض مع لحمة طازجة: 20 شيكل
- بيض مع نقانق: 13 شيكل

### الجبنة
- جبنة بيضاء مع بندورة: 18 شيكل
- جبنة بيضاء مع حبة البركة: 15 شيكل
- جبنة بيضاء مع زعتر أخضر: 17 شيكل
- جبنة بيضاء مع زيت وزعتر: 17 شيكل
- جبنة بيضاء مع زيتون أخضر: 17 شيكل
- جبنة عيمك: 23 شيكل
- جبنة عيمك مع ستيك دجاج: 30 شيكل
- جبنة عيمك مع سلامي: 28 شيكل
- جبنة عيمك مع نقانق: 27 شيكل
- جبنة موزاريلا: 18 شيكل
- جبنة موزاريلا بالدجاج المكسيكي الحار: 28 شيكل
- جبنة موزاريلا مع زيتون أخضر: 20 شيكل
- جبنة موزاريلا مع ستيك الدجاج: 28 شيكل
- جبنة موزاريلا مع سلامي: 25 شيكل
- جبنة موزاريلا مع نقانق: 23 شيكل

### اللحمة والسفيحة
- سفيحة بالبندورة: 15 شيكل
- سفيحة بالطحينية: 15 شيكل
- سفيحة مكس: 15 شيكل
- فاهيتا جبنة: 23 شيكل
- فاهيتا دجاج: 23 شيكل
- كبدة دجاج: 20 شيكل
- لحمة طازجة: 25 شيكل
- مسحب مع جبنة: 25 شيكل
- مسخن دجاج: 22 شيكل

### الصواني
- صواني كبير (شوي): 30 شيكل
- صواني كبير مع خضار: 40 شيكل
- صواني وسط (شوي): 20 شيكل
- صواني وسط مع خضار: 30 شيكل

### الخبز والمناقيش
- خبز الطابون: 1.50 شيكل
- خبز شراك: 1 شيكل
- مناقيش زعتر: 7 شيكل
- 7 طابون: 10 شيكل

### المعجنات الصغيرة
- جبنة بيضاء صغير: 5 شيكل
- جبنة بيضاء مع زعتر صغير: 7 شيكل
- جبنة مع زيتون أخضر صغير: 6 شيكل
- جبنة مع نقانق صغير: 7 شيكل
- ريانة لحمة: 8 شيكل
- سبانخ: 6 شيكل
- عرايس: 8 شيكل
- لفة مسخن: 8 شيكل
- مسحب دجاج: 10 شيكل

### المقبلات
- شيلي متوك: 3 شيكل
- صوص فهيم: 3 شيكل
- علبة باربكيو: 3 شيكل
- علبة زيتون: 2 شيكل
- علبة لفت صغير: 2 شيكل
- علبة مخلل صغير: 2 شيكل
- فلفل مكبوس صغير: 2 شيكل
- نص طبق بيض: 10 شيكل

### المشروبات
- ماء صغير: 2 شيكل
- ماء كبير: 3 شيكل
- كابي صغير: 3 شيكل
- لبن أب: 3 شيكل
- عصير تبوزينا: 4 شيكل
- صودا: 5 شيكل
- مشروب غازي 330: 3 شيكل
- مشروب غازي 1.25: 5 شيكل
- BLUE: 5 شيكل
- TASCO: 5 شيكل
- XL: 5 شيكل
- بافاريا: 5 شيكل

## الردود الخاصة
- التوصيل: "متوفر للعيزرية والمناطق المجاورة"
- الدفع: "كاش أو فيزا داخل المحل"
- ساعات العمل: "من 8 الصبح لـ 2 بالليل، كل يوم"
- صنف غير موجود: "للأسف مش متوفر، بقترح عليك [بديل]"
- في حال طلب "معجنات مناسبات" أخبره أن يتواصل معنا عبر الواتساب 0523668131"""

# ═══════════════════════════════════════════════════════════════════════════
# 🧹 تنظيف تلقائي (Thread)
# ═══════════════════════════════════════════════════════════════════════════

def auto_cleanup():
    if db_orders is None:
        return
        
    today = datetime.now().strftime('%Y-%m-%d')
    # تحقق من التنظيف مرة واحدة يومياً
    if getattr(db, 'last_cleanup', '') != today:
        try:
            yesterday = datetime.now() - timedelta(days=1)
            yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_iso = yesterday.isoformat()
            
            # حذف الطلبات الأقدم من الأمس
            result = db_orders.delete_many({
                'createdAt': {'$lt': yesterday_iso}
            })
            
            if result.deleted_count > 0:
                print(f"🧹 تنظيف تلقائي: تم حذف {result.deleted_count} طلب قديم من MongoDB")
            
            db.last_cleanup = today
        except Exception as e:
            print(f"Error in auto_cleanup: {e}")

def daily_cleanup_loop():
    last_cleanup_date = ""
    while True:
        try:
            jerusalem_tz = pytz.timezone('Asia/Jerusalem')
            now = datetime.now(jerusalem_tz)
            
            hours = now.hour
            minutes = now.minute
            today_date = now.strftime('%Y-%m-%d')
            
            # الساعة 5 فجراً
            if hours == 5 and minutes < 2 and last_cleanup_date != today_date:
                if db_orders is not None:
                    # حذف جميع الطلبات (تصفير يومي)
                    result = db_orders.delete_many({})
                    deleted_count = result.deleted_count
                    
                    # إعادة تعيين العداد (اختياري، لكن يفضل الحفاظ على التسلسل)
                    # db.counter = 1000 
                    
                    last_cleanup_date = today_date
                    print(f'\n🧹 مسح يومي (5:00 فجراً) - تم حذف {deleted_count} طلب من MongoDB\n')
        except Exception as e:
            print(f"Error in cleanup loop: {e}")
        time.sleep(30)

# Start cleanup thread
threading.Thread(target=daily_cleanup_loop, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════
# 🔌 WebSocket Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@sock.route('/ws/notifications')
def websocket_notifications(ws):
    manager.connect(ws)
    try:
        while True:
            data = ws.receive()
            if data:
                try:
                    msg = json.loads(data)
                    if msg.get('type') == 'subscribe' and msg.get('orderId'):
                        order_id = int(msg['orderId'])
                        manager.connect(ws, order_id) # Register for order specific updates
                except:
                    pass
    except Exception:
        pass
    finally:
        manager.disconnect(ws)

@sock.route('/ws/notifications/<int:order_id>')
def websocket_order_notifications(ws, order_id):
    manager.connect(ws, order_id)
    try:
        while True:
            ws.receive()
    except Exception:
        pass
    finally:
        manager.disconnect(ws, order_id)

# ═══════════════════════════════════════════════════════════════════════════
# 🔌 API Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/identify', methods=['POST'])
def identify_customer():
    data = request.json
    fingerprint = data.get('fingerprint')
    
    if not fingerprint:
        return jsonify({"success": False, "error": "Fingerprint required"}), 400
        
    # البحث في MongoDB
    customer = get_customer_data(fingerprint)
    
    if customer:
        print(f"✅ تم التعرف على الزبون: {customer.get('name')} ({fingerprint})")
        return jsonify({
            "success": True,
            "found": True,
            "data": customer
        })
    else:
        print(f"⚠️ زبون جديد: {fingerprint}")
        return jsonify({
            "success": True,
            "found": False
        })

@app.route('/api/chat', methods=['POST'])
def chat_endpoint():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({"success": False, "error": "الرسالة مطلوبة"}), 400

    message = data['message']
    history = data.get('history', [])
    fingerprint = data.get('fingerprint')

    # ✅ استرجاع البيانات الحقيقية من MongoDB (مصدر الحقيقة)
    mongo_customer_data = None
    if fingerprint:
        mongo_customer_data = get_customer_data(fingerprint)

    # دمج البيانات الجديدة القادمة من المتصفح مع القديمة من MongoDB
    client_customer_data = data.get('customerData', {})
    
    # نبدأ بالبيانات من العميل (كاحتياط)
    final_customer_data = client_customer_data.copy() if client_customer_data else {}
    
    # ولكن بيانات MongoDB هي الأصدق والأحدث دائماً
    if mongo_customer_data:
        final_customer_data.update(mongo_customer_data)

    # بناء المحادثة
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ✅ إضافة بيانات الزبون للـ AI
    if final_customer_data:
        print(f"👤 Found customer data for AI: {final_customer_data.get('name')}")
        
        system_injection = f"""
        [SYSTEM MEMORY INJECTION]
        ⚠️ URGENT INSTRUCTION FOR AI:
        The user sending the next message is ALREADY KNOWN.
        - Name: {final_customer_data.get('name', 'Unknown')}
        - Phone: {final_customer_data.get('phone', 'Unknown')}
        - Preferred Order: {final_customer_data.get('orderType', 'Unknown')}
        - Car: {final_customer_data.get('carColor', 'Unknown')}
        - Address: {final_customer_data.get('address', 'Unknown')}
        - Location: {final_customer_data.get('locationName', 'Unknown')}
        
        DO NOT ask for their name. Greet them by name immediately!
        Example: "أهلاً {final_customer_data.get('name')}! شو حابب تطلب اليوم؟"
        """
        messages.append({"role": "system", "content": system_injection})
    
    # إضافة التاريخ (آخر 10 رسائل)
    for msg in history[-10:]:
        messages.append({
            "role": "user" if msg.get('role') == "user" else "assistant",
            "content": msg.get('content')
        })
    
    messages.append({"role": "user", "content": message})

    try:
        # استدعاء OpenAI API مباشرة بدون SDK لتجنب مشاكل Pydantic
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.7
        }
        
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        
        ai_response = response.json()
        reply = ai_response['choices'][0]['message']['content']

        # استخراج بيانات الطلب
        order_match = re.search(r'\[ORDER_DATA\](.*?)\[/ORDER_DATA\]', reply, re.DOTALL)
        order_id = None
        
        if order_match:
            try:
                # Clean up markdown code blocks if present
                raw_json = order_match.group(1).strip()
                if raw_json.startswith('```json'):
                    raw_json = raw_json[7:]
                if raw_json.startswith('```'):
                    raw_json = raw_json[3:]
                if raw_json.endswith('```'):
                    raw_json = raw_json[:-3]
                
                order_data = json.loads(raw_json.strip())
                print(f"📦 Extracted order data: {order_data}")
                
                # ✅ حفظ بيانات الزبون
                if fingerprint:
                    print(f"💾 Saving customer data for {fingerprint}...")
                    save_customer_data(fingerprint, {
                        'name': order_data.get('customer'),
                        'phone': order_data.get('phone'),
                        'orderType': order_data.get('orderType'),
                        'carColor': order_data.get('carInfo'),
                        'address': order_data.get('address'),
                        'locationName': order_data.get('location')
                    })
                else:
                    print("⚠️ No fingerprint provided, skipping customer save")
                
                db.counter += 1
                order = {
                    'id': db.counter,
                    'customerName': order_data.get('customer', 'عميل'),
                    'phone': order_data.get('phone', ''),
                    'items': order_data.get('items', ''),
                    'total': float(order_data.get('total', 0)),
                    'orderType': order_data.get('orderType', 'dine_in'),
                    'location': order_data.get('location', 'غير محدد'),
                    'address': order_data.get('address', ''),
                    'carInfo': order_data.get('carInfo', ''),
                    'deliveryNotes': order_data.get('deliveryNotes', ''),
                    'status': 'new',
                    'createdAt': datetime.now().isoformat(),
                    'updatedAt': datetime.now().isoformat(),
                    'source': 'AI_Chat',
                    'fingerprint': fingerprint  # ✅ حفظ البصمة
                }
                
                # ✅ استخدام الطريقة الجديدة للإضافة
                db.add_order(order)
                order_id = order['id']
                
                print(f"🔔 طلب جديد من AI #{order_id}: {order['customerName']}")

                # إزالة بيانات الطلب من الرد
                reply = re.sub(r'\[ORDER_DATA\].*?\[/ORDER_DATA\]', '', reply, flags=re.DOTALL).strip()
                reply += f"\n\n📋 رقم طلبك: #{order_id}"

            except Exception as e:
                print(f"Error parsing order: {e}")

        return jsonify({
            "success": True,
            "reply": reply,
            "orderId": order_id
        })

    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({
            "success": False,
            "error": "حدث خطأ في الخدمة",
            "reply": "عذراً، حصل خطأ. حاول مرة أخرى"
        }), 500

@app.route('/api/orders', methods=['GET'])
def get_orders():
    auto_cleanup()
    order_type = request.args.get('orderType')
    filtered_orders = db.orders
    
    if order_type and order_type in ['dine_in', 'car_pickup', 'delivery']:
        filtered_orders = [o for o in db.orders if o['orderType'] == order_type]
    
    return jsonify({
        "success": True,
        "orders": filtered_orders,
        "total": len(filtered_orders),
        "byType": {
            "dine_in": len([o for o in db.orders if o['orderType'] == 'dine_in']),
            "car_pickup": len([o for o in db.orders if o['orderType'] == 'car_pickup']),
            "delivery": len([o for o in db.orders if o['orderType'] == 'delivery'])
        }
    })

@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json
    if not data or 'customerName' not in data or 'items' not in data:
        return jsonify({"success": False, "error": "البيانات ناقصة"}), 400
    
    db.counter += 1
    order = {
        'id': db.counter,
        'customerName': data['customerName'],
        'phone': data.get('phone', ''),
        'items': data['items'],
        'total': float(data.get('total', 0)),
        'orderType': data.get('orderType', 'dine_in'),
        'location': data.get('location', 'داخل المحل'),
        'address': data.get('address', ''),
        'carInfo': data.get('carInfo', ''),
        'deliveryNotes': data.get('deliveryNotes', ''),
        'notes': data.get('notes', ''),
        'status': 'new',
        'createdAt': datetime.now().isoformat(),
        'updatedAt': datetime.now().isoformat(),
        'source': 'Manual'
    }
    
    db.add_order(order)
    print(f"📝 طلب يدوي #{order['id']}: {order['customerName']}")
    
    return jsonify({"success": True, "order": order})

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    order = next((o for o in db.orders if o['id'] == order_id), None)
    if not order:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    
    status_text = {
        'new': 'تم استلام طلبك',
        'preparing': 'جاري تحضير طلبك',
        'ready': 'طلبك جاهز للاستلام! 🎉',
        'delivered': 'تم تسليم الطلب',
        'cancelled': 'تم إلغاء الطلب'
    }
    
    return jsonify({
        "success": True,
        "id": order['id'],
        "status": order['status'],
        "items": order['items'],
        "total": order['total'],
        "orderType": order['orderType'],
        "statusText": status_text.get(order['status']),
        "notification": order.get('readyNotification'),
        "updatedAt": order['updatedAt']
    })

@app.route('/api/orders/<int:order_id>', methods=['PATCH'])
def update_order(order_id):
    order = next((o for o in db.orders if o['id'] == order_id), None)
    if not order:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    
    data = request.json
    previous_status = order['status']
    
    if 'status' in data:
        order['status'] = data['status']
        print(f"📝 تحديث #{order['id']}: {order['status']}")
        
        if order['status'] == 'ready' and previous_status != 'ready':
            order_type_msg = {
                'dine_in': 'يمكنك استلامه من الكاونتر',
                'car_pickup': 'سنوصله لسيارتك الآن',
                'delivery': 'جاري توصيله إليك'
            }
            
            msg_text = f"🎉 تم تجهيز طلبك #{order['id']}! {order_type_msg.get(order['orderType'], '')}"
            order['readyNotification'] = {
                'sent': True,
                'message': msg_text,
                'timestamp': datetime.now().isoformat()
            }
            
            # Broadcast WebSocket
            manager.broadcast({
                'type': 'order_ready',
                'orderId': order['id'],
                'message': msg_text,
                'orderType': order['orderType'],
                'customerName': order['customerName'],
                'timestamp': datetime.now().isoformat()
            })
            
            manager.send_to_order(order['id'], {
                'type': 'order_ready',
                'orderId': order['id'],
                'message': msg_text,
                'timestamp': datetime.now().isoformat()
            })
            
    if 'notes' in data:
        order['notes'] = data['notes']
        # Update MongoDB
        db.update_order(order['id'], {'notes': order['notes']})
        
    order['updatedAt'] = datetime.now().isoformat()
    # Update timestamp in MongoDB
    db.update_order(order['id'], {'updatedAt': order['updatedAt']})
    
    return jsonify({"success": True, "order": order})

@app.route('/api/orders/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    # البحث في MongoDB مباشرة
    if db_orders:
        try:
            result = db_orders.delete_one({'id': order_id})
            if result.deleted_count > 0:
                print(f"🗑️ Deleted order #{order_id} from MongoDB")
                return jsonify({"success": True, "message": "تم حذف الطلب"})
        except Exception as e:
            print(f"Error deleting from Mongo: {e}")
            
    return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

@app.route('/api/stats', methods=['GET'])
def get_stats():
    # auto_cleanup() # Removed to avoid heavy operations on every stats call
    
    if not db_orders:
        return jsonify({"success": False, "error": "Database not connected"})
        
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_iso = today.isoformat()
        
        # Count directly from MongoDB
        total_orders = db_orders.count_documents({})
        today_count = db_orders.count_documents({'createdAt': {'$gte': today_iso}})
        
        # Aggregation for status
        status_counts = list(db_orders.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]))
        by_status = {item['_id']: item['count'] for item in status_counts}
        
        # Aggregation for type
        type_counts = list(db_orders.aggregate([
            {"$group": {"_id": "$orderType", "count": {"$sum": 1}}}
        ]))
        by_type = {item['_id']: item['count'] for item in type_counts}
        
        # Calculate revenue (only delivered)
        revenue_pipeline = [
            {"$match": {"status": "delivered", "createdAt": {"$gte": today_iso}}},
            {"$group": {"_id": None, "total": {"$sum": "$total"}}}
        ]
        revenue_result = list(db_orders.aggregate(revenue_pipeline))
        today_revenue = revenue_result[0]['total'] if revenue_result else 0
        
        return jsonify({
            "success": True,
            "stats": {
                "total": total_orders,
                "today": today_count,
                "todayRevenue": today_revenue,
                "byStatus": {
                    "new": by_status.get('new', 0),
                    "preparing": by_status.get('preparing', 0),
                    "ready": by_status.get('ready', 0),
                    "delivered": by_status.get('delivered', 0),
                    "cancelled": by_status.get('cancelled', 0)
                },
                "byType": {
                    "dine_in": by_type.get('dine_in', 0),
                    "car_pickup": by_type.get('car_pickup', 0),
                    "delivery": by_type.get('delivery', 0)
                }
            }
        })
    except Exception as e:
        print(f"Stats Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/orders/poll', methods=['GET'])
def poll_orders():
    since = int(request.args.get('since', 1000))
    # Simple short polling response instead of long polling for Flask simplicity
    # The client can poll every few seconds
    new_orders = [o for o in db.orders if o['id'] > since]
    
    if new_orders:
        last_id = max(o['id'] for o in new_orders)
        return jsonify({
            "hasUpdates": True,
            "orders": new_orders,
            "lastId": last_id
        })
    return jsonify({"hasUpdates": False, "lastId": since})

@app.route('/api/notifications/ready', methods=['GET'])
def get_ready_notifications():
    since_str = request.args.get('since')
    try:
        if since_str:
            since_clean = since_str.replace('Z', '').split('+')[0].split('.')[0]
            since_time = datetime.fromisoformat(since_clean)
        else:
            since_time = datetime.now() - timedelta(minutes=1)
    except:
        since_time = datetime.now() - timedelta(minutes=1)

    ready_orders = []
    for o in db.orders:
        if o['status'] == 'ready' and o.get('readyNotification'):
            try:
                notif_time_str = o['readyNotification']['timestamp'].split('+')[0].split('.')[0]
                notif_time = datetime.fromisoformat(notif_time_str)
                if notif_time > since_time:
                    ready_orders.append(o)
            except:
                pass
    
    return jsonify({
        "success": True,
        "notifications": [
            {
                "orderId": o['id'],
                "message": o['readyNotification']['message'],
                "timestamp": o['readyNotification']['timestamp'],
                "orderType": o.get('orderType', 'dine_in')
            }
            for o in ready_orders
        ]
    })

@app.route('/api/test-db', methods=['GET'])
def test_db_connection():
    """Endpoint to diagnose MongoDB connection"""
    results = {
        "status": "unknown",
        "connection_string_present": bool(MONGODB_URL),
        "client_initialized": mongo_client is not None,
        "collections": {},
        "errors": []
    }
    
    if not mongo_client:
        results["status"] = "failed"
        results["errors"].append("MongoClient not initialized")
        return jsonify(results), 500

    try:
        # 1. Test Ping
        mongo_client.admin.command('ping')
        results["ping"] = "success"
        
        # 2. Check Collections
        db_names = mongo_client.list_database_names()
        results["databases"] = db_names
        
        # Try to connect and write even if not listed (MongoDB lazy creation)
        db = mongo_client['king_of_taboon']
        
        # 3. Test Write/Read
        try:
            db.test_connection.insert_one({"test": "ok", "time": datetime.now().isoformat()})
            doc = db.test_connection.find_one({"test": "ok"})
            
            if doc:
                results["write_read_test"] = "success"
                db.test_connection.delete_many({"test": "ok"})
                results["status"] = "connected"
                
                # Update collections list after write
                results["collections"] = db.list_collection_names()
            else:
                results["write_read_test"] = "failed"
                results["status"] = "warning"
        except Exception as e:
            results["write_read_test"] = f"failed: {str(e)}"
            results["status"] = "error"
            results["errors"].append(f"Write failed: {str(e)}")
        
    except Exception as e:
        results["status"] = "error"
        results["errors"].append(str(e))
        
    return jsonify(results)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "server": "ملك الطابون - Backend (Flask)",
        "version": "3.1.0-flask",
        "orders": len(db.orders),
        "uptime": "running"
    })

@app.route('/api/cleanup', methods=['DELETE'])
def manual_cleanup():
    if db_orders:
        try:
            # حذف جميع الطلبات
            result = db_orders.delete_many({})
            count = result.deleted_count
            # db.counter = 1000 # اختياري
            print(f"🧹 تم مسح {count} طلب من MongoDB يدوياً")
            return jsonify({"success": True, "message": f"تم مسح {count} طلب من قاعدة البيانات"})
        except Exception as e:
            print(f"Error in manual_cleanup: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
            
    return jsonify({"success": False, "error": "Database not connected"}), 500

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 Startup
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║   🔥  ملك الطابون - Backend المركزي v3.1 (Flask Edition)                  ║
║                                                                           ║
║   📡 السيرفر يعمل على: http://localhost:3000                             ║
║   ✨ تم الاستغناء عن Pydantic/FastAPI لضمان التوافقية مع Python 3.14      ║
║   📦 يخدم المواقع الأمامية مباشرة (Monolith)                              ║
║      - العملاء: http://localhost:3000                                     ║
║      - العمال:  http://localhost:3000/staff                               ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
    """)
    # Flask development server
    port = int(os.environ.get('PORT', 3000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
