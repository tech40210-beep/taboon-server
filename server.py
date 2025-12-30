"""
═══════════════════════════════════════════════════════════════════════════
🔥 ملك الطابون - Backend المركزي (العقل) - النسخة المطورة - Python
═══════════════════════════════════════════════════════════════════════════

هذا هو الوسيط الآمن بين موقع العملاء وموقع العمال

المسؤوليات:
1. حماية مفتاح OpenAI API
2. التواصل مع الذكاء الاصطناعي
3. استقبال وتخزين الطلبات
4. توزيع البيانات للموقعين
5. Rate Limiting للحماية من الإساءة
6. مسح تلقائي للطلبات القديمة
7. ✅ دعم ثلاثة أنواع من الزبائن
8. ✅ WebSocket للإشعارات الفورية للعملاء

═══════════════════════════════════════════════════════════════════════════
"""

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
import json
import re
import asyncio
import pytz
from openai import OpenAI
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
# 🔐 الإعدادات الحساسة
# ═══════════════════════════════════════════════════════════════════════════

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

if not OPENAI_API_KEY:
    print('⚠️  تحذير: مفتاح OpenAI غير مُعد! أضفه في متغيرات البيئة')

# إنشاء OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 إنشاء التطبيق
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="ملك الطابون - Backend المركزي",
    version="3.1.0",
    description="Professional Restaurant Backend with AI Integration + WebSocket Notifications"
)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════
# 📦 قاعدة البيانات المؤقتة
# ═══════════════════════════════════════════════════════════════════════════

class Database:
    def __init__(self):
        self.orders: List[Dict] = []
        self.counter: int = 1000
        self.last_cleanup: str = datetime.now().strftime('%Y-%m-%d')
        self.last_known_id: int = 1000

db = Database()

# ═══════════════════════════════════════════════════════════════════════════
# 🔌 WebSocket Connection Manager - إدارة اتصالات العملاء
# ═══════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        # قائمة الاتصالات النشطة مع رقم الطلب لكل عميل
        self.active_connections: Dict[int, List[WebSocket]] = {}
        # جميع الاتصالات للبث العام
        self.all_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket, order_id: int = None):
        """قبول اتصال جديد"""
        await websocket.accept()
        self.all_connections.append(websocket)
        
        if order_id:
            if order_id not in self.active_connections:
                self.active_connections[order_id] = []
            self.active_connections[order_id].append(websocket)
            print(f"🔗 عميل متصل لمتابعة الطلب #{order_id}")
        else:
            print(f"🔗 عميل متصل (بدون طلب محدد)")
    
    def disconnect(self, websocket: WebSocket, order_id: int = None):
        """قطع الاتصال"""
        if websocket in self.all_connections:
            self.all_connections.remove(websocket)
        
        if order_id and order_id in self.active_connections:
            if websocket in self.active_connections[order_id]:
                self.active_connections[order_id].remove(websocket)
            if not self.active_connections[order_id]:
                del self.active_connections[order_id]
        print(f"🔌 عميل قطع الاتصال")
    
    async def send_to_order(self, order_id: int, message: dict):
        """إرسال رسالة لعميل طلب محدد"""
        if order_id in self.active_connections:
            for connection in self.active_connections[order_id]:
                try:
                    await connection.send_json(message)
                    print(f"📤 تم إرسال إشعار للطلب #{order_id}")
                except Exception as e:
                    print(f"⚠️ خطأ في الإرسال: {e}")
    
    async def broadcast(self, message: dict):
        """إرسال رسالة لجميع العملاء المتصلين"""
        disconnected = []
        for connection in self.all_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # إزالة الاتصالات المنقطعة
        for conn in disconnected:
            if conn in self.all_connections:
                self.all_connections.remove(conn)
        
        if message.get('type') == 'order_ready':
            print(f"📢 تم بث إشعار جاهزية للجميع - الطلب #{message.get('orderId')}")

manager = ConnectionManager()

# ═══════════════════════════════════════════════════════════════════════════
# 📋 Pydantic Models
# ═══════════════════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []

class OrderCreate(BaseModel):
    customerName: str
    phone: Optional[str] = ""
    items: str
    total: float = 0
    orderType: str = "dine_in"
    location: str = "داخل المحل"
    address: Optional[str] = ""
    carInfo: Optional[str] = ""
    deliveryNotes: Optional[str] = ""
    notes: Optional[str] = ""

class OrderUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════
# 🧹 تنظيف تلقائي
# ═══════════════════════════════════════════════════════════════════════════

def auto_cleanup():
    """تنظيف الطلبات القديمة"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    if today != db.last_cleanup:
        yesterday = datetime.now() - timedelta(days=1)
        yesterday = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        
        before = len(db.orders)
        db.orders = [o for o in db.orders if datetime.fromisoformat(o['createdAt']) >= yesterday]
        
        if before != len(db.orders):
            print(f"🧹 تنظيف تلقائي: حذف {before - len(db.orders)} طلب قديم")
        
        db.last_cleanup = today

# ═══════════════════════════════════════════════════════════════════════════
# 🕐 مسح يومي الساعة 5 فجراً بتوقيت القدس
# ═══════════════════════════════════════════════════════════════════════════

last_cleanup_date = ""

async def daily_cleanup_at_5am():
    """مسح جميع الطلبات الساعة 5:00 فجراً بتوقيت القدس"""
    global last_cleanup_date
    
    while True:
        try:
            # الحصول على الوقت بتوقيت القدس
            jerusalem_tz = pytz.timezone('Asia/Jerusalem')
            now = datetime.now(jerusalem_tz)
            
            hours = now.hour
            minutes = now.minute
            today_date = now.strftime('%Y-%m-%d')
            
            # إذا كانت الساعة 5:00-5:01 فجراً ولم يتم المسح اليوم
            if hours == 5 and minutes < 2 and last_cleanup_date != today_date:
                deleted_count = len(db.orders)
                db.orders = []
                db.counter = 1000
                last_cleanup_date = today_date
                
                print('\n╔════════════════════════════════════════════════════════════╗')
                print('║  🧹 مسح يومي - الساعة 5:00 فجراً بتوقيت القدس              ║')
                print(f'║  📊 تم حذف جميع الطلبات: {deleted_count} طلب                         ║')
                print('║  ✅ النظام جاهز ليوم جديد                                  ║')
                print('╚════════════════════════════════════════════════════════════╝\n')
        
        except Exception as e:
            print(f"خطأ في المسح اليومي: {e}")
        
        # فحص كل 30 ثانية
        await asyncio.sleep(30)

# ═══════════════════════════════════════════════════════════════════════════
# 🤖 System Prompt للذكاء الاصطناعي
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """# وكيل طلبات مطعم ملك الطابون

## هويتك
أنت مساعد طلبات مطعم "ملك الطابون والمعجنات" في العيزرية. تستقبل طلبات الزبائن باللهجة الفلسطينية.

## معلومات المطعم
- الاسم: ملك الطابون
- العنوان: العيزرية - دوار وادي النار
- ساعات العمل: 8:00 صباحاً - 2:00 بعد منتصف الليل (يومياً)
- وقت التحضير: 7-10 دقيقة الوجبة دون وقت التوصيل
- التوصيل: متوفر للعيزرية والمناطق المجاورة
- الدفع: كاش أو فيزا داخل المحل فقط
- التوصيل لأماكن في العيزرية ب شيكل 15 والسواحرة ب 20 شيكل

## قواعد السلوك
1. تحدث بلهجة فلسطينية بسيطة وودودة
2. كن مختصراً - لا تكتب رسائل طويلة
3. لا تعرض القائمة كاملة - اعرض فقط خيارات الصنف المطلوب
4. استخدم إيموجي واحد أو اثنين فقط
5. لا تخترع أصناف غير موجودة ولا تغير الأسعار
6. فقط لمن هو بالمحل او بالسيارة أطلب منه الاسم + الطلب.
7. قم بإخبار الزبون بالسعر مع طلب التأكيد
8. بمجرد التأكيد, أطلب منه إستلام الطلب بعد 7-10 دقائق, طلبات التوصيل تستغرق 10-20 دقيقة حسب الموقع والطلب
9. في حال طلب  "معجنات مناسبات" أخبره أن يتواصل معنا عبر الواتساب 0523668131

## خاص لطلبيات التوصيل
- اطلب منه رقم الجوال (إجباري) ولا حاجة للإسم. 
- اخذ عنوان الموقع واسم البيت او مكان العمل. 
- اخبارهم ان التوصيل يكلف  10-20 شيكل حسب الموقع بأماكن العيزرية أو السواحرة.

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
- العنوان بالتفصيل (الحي/الشارع/أقرب نقطة معروفة)
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
# 🔌 WebSocket Endpoint - نقطة اتصال العملاء
# ═══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """اتصال WebSocket للإشعارات العامة"""
    await manager.connect(websocket)
    try:
        while True:
            # إبقاء الاتصال مفتوح
            data = await websocket.receive_text()
            # يمكن للعميل إرسال رقم الطلب لمتابعته
            try:
                msg = json.loads(data)
                if msg.get('type') == 'subscribe' and msg.get('orderId'):
                    order_id = int(msg['orderId'])
                    if order_id not in manager.active_connections:
                        manager.active_connections[order_id] = []
                    manager.active_connections[order_id].append(websocket)
                    print(f"📌 العميل اشترك لمتابعة الطلب #{order_id}")
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.websocket("/ws/notifications/{order_id}")
async def websocket_order_notifications(websocket: WebSocket, order_id: int):
    """اتصال WebSocket لمتابعة طلب محدد"""
    await manager.connect(websocket, order_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, order_id)

# ═══════════════════════════════════════════════════════════════════════════
# 🔌 API Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
@limiter.limit("20/minute")
async def chat_endpoint(request: Request, chat_req: ChatRequest):
    """محادثة مع الذكاء الاصطناعي"""
    try:
        if not chat_req.message:
            raise HTTPException(status_code=400, detail="الرسالة مطلوبة")
        
        # بناء المحادثة
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # إضافة التاريخ (آخر 10 رسائل)
        if chat_req.history:
            for msg in chat_req.history[-10:]:
                messages.append({
                    "role": "user" if msg.role == "user" else "assistant",
                    "content": msg.content
                })
        
        messages.append({"role": "user", "content": chat_req.message})
        
        # استدعاء OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        
        reply = response.choices[0].message.content
        
        # استخراج بيانات الطلب
        order_match = re.search(r'\[ORDER_DATA\](.*?)\[/ORDER_DATA\]', reply, re.DOTALL)
        order_id = None
        
        if order_match:
            try:
                order_data = json.loads(order_match.group(1).strip())
                
                # إنشاء الطلب
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
                    'source': 'AI_Chat'
                }
                
                db.orders.insert(0, order)
                order_id = order['id']
                
                # عرض معلومات الطلب
                order_type_labels = {
                    'dine_in': '🏠 داخل المحل',
                    'car_pickup': '🚗 بالسيارة',
                    'delivery': '🛵 توصيل'
                }
                
                print(f"\n{'═' * 50}")
                print(f"🔔 طلب جديد #{order['id']} - {order_type_labels.get(order['orderType'], 'غير محدد')}")
                print(f"{'═' * 50}")
                print(f"   👤 الاسم: {order['customerName']}")
                if order['phone']:
                    print(f"   📱 الجوال: {order['phone']}")
                print(f"   🍕 الطلب: {order['items']}")
                print(f"   💰 المبلغ: {order['total']} شيكل")
                
                if order['orderType'] == 'car_pickup' and order['carInfo']:
                    print(f"   🚗 السيارة: {order['carInfo']}")
                
                if order['orderType'] == 'delivery':
                    print(f"   📍 الموقع: {order['location']}")
                    print(f"   🏠 العنوان: {order['address']}")
                    if order['deliveryNotes']:
                        print(f"   📝 ملاحظات: {order['deliveryNotes']}")
                print(f"{'═' * 50}\n")
                
                # إزالة بيانات الطلب من الرد
                reply = re.sub(r'\[ORDER_DATA\].*?\[/ORDER_DATA\]', '', reply, flags=re.DOTALL).strip()
                reply += f"\n\n📋 رقم طلبك: #{order_id}"
                
            except Exception as e:
                print(f"Error parsing order: {e}")
        
        return {
            "success": True,
            "reply": reply,
            "orderId": order_id
        }
        
    except Exception as e:
        print(f"Chat Error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "حدث خطأ في الخدمة",
                "reply": "عذراً، حصل خطأ. حاول مرة أخرى"
            }
        )

@app.get("/api/orders")
@limiter.limit("60/minute")
async def get_orders(request: Request, orderType: Optional[str] = None):
    """جلب جميع الطلبات"""
    auto_cleanup()
    
    filtered_orders = db.orders
    
    if orderType and orderType in ['dine_in', 'car_pickup', 'delivery']:
        filtered_orders = [o for o in db.orders if o['orderType'] == orderType]
    
    return {
        "success": True,
        "orders": filtered_orders,
        "total": len(filtered_orders),
        "byType": {
            "dine_in": len([o for o in db.orders if o['orderType'] == 'dine_in']),
            "car_pickup": len([o for o in db.orders if o['orderType'] == 'car_pickup']),
            "delivery": len([o for o in db.orders if o['orderType'] == 'delivery'])
        }
    }

@app.post("/api/orders")
@limiter.limit("60/minute")
async def create_order(request: Request, order_create: OrderCreate):
    """إنشاء طلب يدوي"""
    if not order_create.customerName or not order_create.items:
        raise HTTPException(status_code=400, detail="اسم العميل والطلب مطلوبان")
    
    db.counter += 1
    order = {
        'id': db.counter,
        'customerName': order_create.customerName,
        'phone': order_create.phone or '',
        'items': order_create.items,
        'total': order_create.total,
        'orderType': order_create.orderType,
        'location': order_create.location,
        'address': order_create.address or '',
        'carInfo': order_create.carInfo or '',
        'deliveryNotes': order_create.deliveryNotes or '',
        'notes': order_create.notes or '',
        'status': 'new',
        'createdAt': datetime.now().isoformat(),
        'updatedAt': datetime.now().isoformat(),
        'source': 'Manual'
    }
    
    db.orders.insert(0, order)
    print(f"📝 طلب يدوي #{order['id']}: {order['customerName']} - {order['orderType']}")
    
    return {"success": True, "order": order}

@app.get("/api/orders/{order_id}")
async def get_order(order_id: int):
    """جلب طلب واحد"""
    order = next((o for o in db.orders if o['id'] == order_id), None)
    
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    
    status_text = {
        'new': 'تم استلام طلبك',
        'preparing': 'جاري تحضير طلبك',
        'ready': 'طلبك جاهز للاستلام! 🎉',
        'delivered': 'تم تسليم الطلب',
        'cancelled': 'تم إلغاء الطلب'
    }
    
    return {
        "success": True,
        "id": order['id'],
        "status": order['status'],
        "items": order['items'],
        "total": order['total'],
        "orderType": order['orderType'],
        "statusText": status_text.get(order['status']),
        "notification": order.get('readyNotification'),
        "updatedAt": order['updatedAt']
    }

@app.patch("/api/orders/{order_id}")
async def update_order(order_id: int, update: OrderUpdate):
    """تحديث حالة الطلب - مع إرسال WebSocket"""
    order = next((o for o in db.orders if o['id'] == order_id), None)
    
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    
    valid_statuses = ['new', 'preparing', 'ready', 'delivered', 'cancelled']
    previous_status = order['status']
    
    if update.status:
        if update.status not in valid_statuses:
            raise HTTPException(status_code=400, detail="حالة غير صالحة")
        
        order['status'] = update.status
        print(f"📝 تحديث #{order['id']}: {update.status}")
        
        # ✅ إشعار عند الجاهزية - إرسال WebSocket
        if update.status == 'ready' and previous_status != 'ready':
            order_type_msg = {
                'dine_in': 'يمكنك استلامه من الكاونتر',
                'car_pickup': 'سنوصله لسيارتك الآن',
                'delivery': 'جاري توصيله إليك'
            }
            
            notification_message = f"🎉 تم تجهيز طلبك #{order['id']}! {order_type_msg.get(order['orderType'], '')}"
            
            order['readyNotification'] = {
                'sent': True,
                'message': notification_message,
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"🔔 إشعار جاهز للعميل: {order['customerName']} - طلب #{order['id']}")
            
            # ✅ إرسال الإشعار عبر WebSocket لجميع العملاء المتصلين
            await manager.broadcast({
                'type': 'order_ready',
                'orderId': order['id'],
                'message': notification_message,
                'orderType': order['orderType'],
                'customerName': order['customerName'],
                'timestamp': datetime.now().isoformat()
            })
            
            # إرسال للمتابعين المحددين لهذا الطلب
            await manager.send_to_order(order['id'], {
                'type': 'order_ready',
                'orderId': order['id'],
                'message': notification_message,
                'orderType': order['orderType'],
                'timestamp': datetime.now().isoformat()
            })
    
    if update.notes is not None:
        order['notes'] = update.notes
    
    order['updatedAt'] = datetime.now().isoformat()
    
    return {"success": True, "order": order}

@app.delete("/api/orders/{order_id}")
async def delete_order(order_id: int):
    """حذف طلب"""
    order_index = next((i for i, o in enumerate(db.orders) if o['id'] == order_id), None)
    
    if order_index is None:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    
    deleted = db.orders.pop(order_index)
    print(f"🗑️ حذف #{deleted['id']}")
    
    return {"success": True, "message": "تم حذف الطلب"}

@app.get("/api/stats")
async def get_stats():
    """إحصائيات الطلبات"""
    auto_cleanup()
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_orders = [o for o in db.orders if datetime.fromisoformat(o['createdAt']) >= today]
    delivered_today = [o for o in today_orders if o['status'] == 'delivered']
    
    return {
        "success": True,
        "stats": {
            "total": len(db.orders),
            "today": len(today_orders),
            "todayRevenue": sum(o['total'] for o in delivered_today),
            "byStatus": {
                "new": len([o for o in db.orders if o['status'] == 'new']),
                "preparing": len([o for o in db.orders if o['status'] == 'preparing']),
                "ready": len([o for o in db.orders if o['status'] == 'ready']),
                "delivered": len([o for o in db.orders if o['status'] == 'delivered']),
                "cancelled": len([o for o in db.orders if o['status'] == 'cancelled'])
            },
            "byType": {
                "dine_in": len([o for o in db.orders if o['orderType'] == 'dine_in']),
                "car_pickup": len([o for o in db.orders if o['orderType'] == 'car_pickup']),
                "delivery": len([o for o in db.orders if o['orderType'] == 'delivery'])
            }
        }
    }

@app.get("/api/orders/poll")
async def poll_orders(since: int = 1000):
    """Long polling للتحديثات"""
    new_orders = [o for o in db.orders if o['id'] > since]
    
    if new_orders:
        last_id = max(o['id'] for o in new_orders)
        return {
            "hasUpdates": True,
            "orders": new_orders,
            "lastId": last_id
        }
    
    await asyncio.sleep(1)
    return {"hasUpdates": False, "lastId": since}

@app.get("/api/notifications/ready")
async def get_ready_notifications(since: Optional[str] = None):
    """إشعارات الطلبات الجاهزة"""
    try:
        if since:
            # إزالة الـ timezone لتجنب مشاكل المقارنة
            since_clean = since.replace('Z', '').split('+')[0].split('.')[0]
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
    
    return {
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
    }

@app.get("/api/health")
async def health_check():
    """فحص صحة السيرفر"""
    return {
        "status": "ok",
        "server": "ملك الطابون - Backend",
        "version": "3.1.0",
        "orders": len(db.orders),
        "websocket_connections": len(manager.all_connections),
        "uptime": "running"
    }

@app.delete("/api/cleanup")
async def manual_cleanup():
    """مسح جميع الطلبات"""
    count = len(db.orders)
    db.orders = []
    db.counter = 1000
    print(f"🧹 تم مسح {count} طلب")
    return {"success": True, "message": f"تم مسح {count} طلب"}

# ═══════════════════════════════════════════════════════════════════════════
# 🚀 Startup Event
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup_event():
    """تشغيل المهام عند بدء التطبيق"""
    # بدء المسح اليومي
    asyncio.create_task(daily_cleanup_at_5am())
    
    print("""
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║   🔥  ملك الطابون - Backend المركزي v3.1 (Python + WebSocket)            ║
║                                                                           ║
║   📡 السيرفر يعمل على: http://localhost:3000                             ║
║                                                                           ║
║   ═══════════════════════════════════════════════════════════════════════ ║
║                                                                           ║
║   🔌 APIs للموقع الأول (العملاء):                                         ║
║      POST /api/chat         → محادثة مع الذكاء الاصطناعي                  ║
║      WS   /ws/notifications → إشعارات فورية للعملاء ✨ جديد               ║
║      WS   /ws/notifications/{order_id} → متابعة طلب محدد ✨               ║
║                                                                           ║
║   📦 APIs للموقع الثاني (العمال):                                         ║
║      GET  /api/orders       → جلب كل الطلبات                              ║
║      GET  /api/orders?orderType=delivery → فلترة حسب النوع                 ║
║      POST /api/orders       → إنشاء طلب يدوي                              ║
║      PATCH /api/orders/:id  → تحديث حالة طلب (يرسل WebSocket)             ║
║      DELETE /api/orders/:id → حذف طلب                                     ║
║      GET  /api/stats        → الإحصائيات                                  ║
║      GET  /api/orders/poll  → تحديثات فورية                               ║
║                                                                           ║
║   ✅ أنواع الطلبات المدعومة:                                              ║
║      🏠 dine_in     → داخل المحل                                          ║
║      🚗 car_pickup  → بالسيارة                                            ║
║      🛵 delivery    → توصيل للمنزل                                        ║
║                                                                           ║
║   ❤️  GET /api/health        → فحص صحة السيرفر                             ║
║                                                                           ║
║   جاهز لخدمة الموقعين! 🚀                                                 ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)