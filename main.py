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
def home(): return "Бот ГДЗ работает: статус OK"

def run_web():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        log(f"⚠️ Ошибка веб-сервера: {e}")

def keep_alive():
    log("🌐 Запуск веб-сервера для UptimeRobot...")
    Thread(target=run_web, daemon=True).start()

# --- СИСТЕМА ЛОГИРОВАНИЯ ---
def log(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# --- ОСНОВНОЙ КЛАСС БОТА ---
load_dotenv()

class UltimateGdzBot:
    def __init__(self):
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-2.5-flash"
        self.gemini_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={self.gemini_key}"
        self.offset = 0
        self._init_session()
        
        self.system_prompt = (
            "Ты — эксперт ГДЗ. Реши задачи подробно: Дано, Решение, Ответ. "
            "Используй формулы и знаки (√, ^, π). Жирный текст: **Текст**. "
            "НЕ используй # и >. Каждую задачу отделяй чертой ------------------"
        )
        log(f"🚀 Бот инициализирован. Модель: {self.model_name}")

    def _init_session(self):
        """Создание новой сессии при сетевых сбоях"""
        self.session = requests.Session()
        # Адаптер для стабильности соединений
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        self.session.mount('https://', adapter)
        log("🔄 Сессия обновлена")

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
            prefix = f"🔹 **Часть {index + 1}/{len(parts)}**\n\n" if len(parts) > 1 else ""
            payload = {"chat_id": chat_id, "text": prefix + part, "parse_mode": "Markdown"}
            try:
                r = self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
                if not r.json().get("ok"):
                    payload.pop("parse_mode")
                    self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
                log(f"✅ Сообщение {index + 1} отправлено")
            except:
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
