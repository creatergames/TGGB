import os
import time
import requests
import base64
import io
import datetime
from PIL import Image
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- БЛОК ОЖИВЛЕНИЯ 24/7 ---
app = Flask('')
@app.route('/')
def home(): return "Бот ГДЗ: Ротация 10 ключей активна"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    log("🌐 Запуск веб-сервера для Render/UptimeRobot...")
    Thread(target=run_web, daemon=True).start()

# --- СИСТЕМА ЛОГИРОВАНИЯ ---
def log(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# --- ОСНОВНОЙ КЛАСС БОТА ---
load_dotenv()

class MultiKeyGdzBot:
    def __init__(self):
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        # Получаем список ключей из одной переменной, разделенной запятыми
        raw_keys = os.getenv("GEMINI_API_KEYS", "")
        self.gemini_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        
        self.current_key_index = 0
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-2.5-flash"
        self.offset = 0
        self._init_session()
        
        self.system_prompt = (
            "Ты — эксперт ГДЗ. Реши задачи подробно: Дано, Решение, Ответ. "
            "Используй формулы и знаки (√, ^, π). Жирный текст: **Текст**. "
            "НЕ используй # и >. Каждую задачу отделяй чертой ------------------"
        )
        log(f"🚀 Бот запущен. Загружено ключей: {len(self.gemini_keys)}")

    def _init_session(self):
        self.session = requests.Session()
        self.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

    def get_current_url(self):
        key = self.gemini_keys[self.current_key_index]
        return f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={key}"

    def clean_text(self, text):
        if not text: return ""
        for char in ["#", "`", "~~", "---", ">", "\\"]:
            text = text.replace(char, "")
        return text

    def send_split_message(self, chat_id, text):
        text = self.clean_text(text)
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        for index, part in enumerate(parts):
            header = "💎 **ВАШЕ ПОДРОБНОЕ РЕШЕНИЕ** 💎\n\n"
            prefix = f"🔹 **Часть {index + 1}/{len(parts)}**\n\n" if len(parts) > 1 else ""
            payload = {"chat_id": chat_id, "text": header + prefix + part, "parse_mode": "Markdown"}
            try:
                r = self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
                if not r.json().get("ok"):
                    payload.pop("parse_mode")
                    self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
            except: pass

    def call_gemini(self, text, img_bytes=None):
        parts = [{"text": f"{self.system_prompt}\nЗапрос: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096}}

        # Пробуем по очереди все ключи, если ловим 429
        for _ in range(len(self.gemini_keys)):
            try:
                log(f"📡 Запрос (Ключ №{self.current_key_index + 1})...")
                r = self.session.post(self.get_current_url(), json=payload, timeout=90)
                
                if r.status_code == 429:
                    log(f"⏳ Ключ №{self.current_key_index + 1} исчерпан. Переключаюсь...")
                    self.current_key_index = (self.current_key_index + 1) % len(self.gemini_keys)
                    continue # Пробуем следующий ключ в этом же цикле
                
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                log(f"💥 Ошибка: {e}")
                self.current_key_index = (self.current_key_index + 1) % len(self.gemini_keys)
                time.sleep(2)
        
        return "❌ К сожалению, ВСЕ 10 ключей временно исчерпали лимит. Попробуйте через 15-20 минут."

    def run(self):
        log("🛰 Слушаю Telegram...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}, timeout=30)
                updates = r.json().get("result", [])
                for upd in updates:
                    self.offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    chat_id = msg["chat"]["id"]
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})

                    img_data = None
                    if "photo" in msg:
                        file_id = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": file_id}).json()
                        img_raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        img = Image.open(io.BytesIO(img_raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    ans = self.call_gemini(msg.get("text", msg.get("caption", "Реши")), img_data)
                    self.send_split_message(chat_id, ans)
                            
            except Exception as e:
                log(f"🛑 Ошибка цикла: {e}")
                time.sleep(5)

if __name__ == "__main__":
    keep_alive()
    MultiKeyGdzBot().run()
                log("❌ Ошибка при отправке сообщения")

    def call_gemini(self, text, img_bytes=None, retries=3):
        parts = [{"text": f"{self.system_prompt}\nЗапрос: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096}}

        for attempt in range(retries):
            try:
                log(f"📡 Запрос к Gemini (попытка {attempt + 1})...")
                r = self.session.post(self.gemini_url, json=payload, timeout=90)
                if r.status_code == 429:
                    time.sleep(15 * (attempt + 1))
                    continue
                data = r.json()
                return data['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                log(f"💥 Ошибка Gemini: {e}")
                time.sleep(5)
        return "❌ Ошибка ИИ после нескольких попыток."

    def run(self):
        log("🛰 Бот запущен...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}, timeout=30)
                updates = r.json().get("result", [])
                
                for upd in updates:
                    self.offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    
                    chat_id = msg["chat"]["id"]
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})

                    if "photo" in msg:
                        log(f"📸 Обработка фото для {chat_id}")
                        file_id = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": file_id}).json()
                        img_raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        
                        img = Image.open(io.BytesIO(img_raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        
                        ans = self.call_gemini(msg.get("caption", "Реши задачу подробно"), buf.getvalue())
                        self.send_split_message(chat_id, ans)
                    
                    elif "text" in msg:
                        if msg["text"] == "/start":
                            self.send_split_message(chat_id, "Пришли фото задач!")
                        else:
                            ans = self.call_gemini(msg["text"])
                            self.send_split_message(chat_id, ans)
                            
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                log(f"📡 Сетевая ошибка: {e}. Пересоздание сессии...")
                self._init_session() # Сброс сессии для устранения SSL Record Layer Failure
                time.sleep(5)
            except Exception as e:
                log(f"🛑 Ошибка: {e}")
                time.sleep(5)

if __name__ == "__main__":
    keep_alive()
    UltimateGdzBot().run()
