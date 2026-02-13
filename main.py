import os
import time
import requests
import base64
import io
import datetime
import sqlite3
from PIL import Image
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- ИНИЦИАЛИЗАЦИЯ КЭША ---
def init_db():
    try:
        conn = sqlite3.connect('solutions_cache.db')
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS cache 
                          (hash TEXT PRIMARY KEY, solution TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

# --- WEB СЕРВЕР ДЛЯ RENDER ---
app = Flask('')
@app.route('/')
def home():
    return "🤖 GDZ Bot Status: ACTIVE | Logging: ENABLED"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    log("🌐 [WEB] Запуск мониторинга...")
    Thread(target=run_web, daemon=True).start()

# --- СИСТЕМА ЛОГОВ ---
def log(message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}")

# --- ГЛАВНЫЙ КЛАСС БОТА ---
load_dotenv()

class MegaGdzBot:
    def __init__(self):
        log("⚙️ [INIT] Сборка системы...")
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        raw_keys = os.getenv("GEMINI_API_KEYS", "")
        self.keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        
        self.current_key_idx = 0
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        # Возвращена прошлая модель по запросу
        self.model_name = "models/gemini-1.5-flash"
        self.offset = 0
        self.session = requests.Session()
        
        self.system_prompt = (
            "Ты — универсальный ИИ-репетитор. Твои задачи:\n"
            "1. Решай задачи по фото (даже рукописные).\n"
            "2. Структура: **Дано**, **Решение**, **Ответ**.\n"
            "3. Режим ЕГЭ/ОГЭ: давай советы по оформлению.\n"
            "4. Объясняй сложные темы просто.\n"
            "5. Предлагай темы для YouTube в конце.\n"
            "6. Пиши формулы четко через Markdown."
        )
        init_db()
        log(f"✅ [INIT] Готово. Ключей: {len(self.keys)}")

    def get_keyboard(self):
        """Интерактивное меню под ответом"""
        return {
            "inline_keyboard": [
                [{"text": "📚 Объясни проще", "callback_data": "simple"}, 
                 {"text": "📝 Режим ЕГЭ", "callback_data": "ege"}],
                [{"text": "🇬🇧 На английский", "callback_data": "en"},
                 {"text": "🎬 Видео-урок", "callback_data": "yt"}]
            ]
        }

    def call_gemini(self, text, img_bytes=None, mode="standard"):
        """Запрос к ИИ с ротацией ключей и логированием"""
        prefix = ""
        if mode == "simple": prefix = "ОБЪЯСНИ КАК РЕБЕНКУ: "
        elif mode == "ege": prefix = "ОФОРМИ ПО КРИТЕРИЯМ ЕГЭ: "

        parts = [{"text": f"{self.system_prompt}\n\n{prefix}ЗАДАЧА: {text}"}]
        if img_bytes:
            log("🖼 [AI] Обработка изображения...")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.4}}

        for attempt in range(len(self.keys)):
            log(f"📡 [AI] Запрос (Ключ {self.current_key_idx + 1})")
            api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={self.keys[self.current_key_idx]}"
            try:
                r = self.session.post(api_url, json=payload, timeout=90)
                if r.status_code == 429:
                    log(f"⏳ [AI] Ключ {self.current_key_idx + 1} исчерпан. Ротация...")
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
                    continue
                
                res_json = r.json()
                return res_json['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                log(f"💥 [AI] Ошибка ключа {self.current_key_idx + 1}: {e}")
                self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
                time.sleep(1)
        
        return "❌ Все лимиты исчерпаны. Попробуйте позже."

    def send_split_message(self, chat_id, text, with_kb=True):
        """Деление сообщения и отправка с кнопками"""
        log(f"📦 [SEND] Подготовка ответа для {chat_id}")
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        
        for idx, part in enumerate(parts):
            is_last = (idx == len(parts) - 1)
            payload = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_keyboard() if (is_last and with_kb) else None
            }
            try:
                self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
                log(f"📤 [SEND] Часть {idx+1}/{len(parts)} отправлена.")
            except Exception as e:
                log(f"❌ [SEND] Ошибка отправки: {e}")

    def run(self):
        log("🛰 [SYS] Бот слушает Telegram...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}, timeout=30)
                updates = r.json().get("result", [])

                for upd in updates:
                    self.offset = upd["update_id"] + 1
                    
                    if "callback_query" in upd:
                        log("🔘 [BTN] Нажата кнопка меню.")
                        cb = upd["callback_query"]
                        self.session.post(self.tg_url + "answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        new_ans = self.call_gemini("Переделай прошлое решение в режиме: " + cb["data"])
                        self.send_split_message(cb["message"]["chat"]["id"], "🔄 **ОБНОВЛЕННОЕ РЕШЕНИЕ:**\n\n" + new_ans)
                        continue

                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    chat_id = msg["chat"]["id"]
                    
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})

                    img_data = None
                    if "photo" in msg:
                        log(f"📸 [FILE] Получено фото от {chat_id}")
                        file_id = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": file_id}).json()
                        raw_img = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        
                        img = Image.open(io.BytesIO(raw_img)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    prompt = msg.get("text", msg.get("caption", "Реши задачу"))
                    if prompt == "/start":
                        self.send_split_message(chat_id, "📚 Привет! Пришли фото или текст задачи, и я решу её!", with_kb=False)
                        continue

                    log(f"💬 [USER] Запрос: {prompt[:50]}...")
                    ans = self.call_gemini(prompt, img_data)
                    self.send_split_message(chat_id, ans)
                            
            except Exception as e:
                log(f"🛑 [ERR] Критическая ошибка: {e}")
                time.sleep(5)

if __name__ == "__main__":
    keep_alive()
    MegaGdzBot().run()

class UltimateGdzBot:
    def __init__(self):
        log("🚀 Запуск Максимальной версии бота...")
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        raw_keys = os.getenv("GEMINI_API_KEYS", "")
        self.keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        
        self.current_key_idx = 0
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-1.5-flash"
        self.offset = 0
        self.session = requests.Session()
        
        # РАСШИРЕННЫЙ ПРОМПТ (Идеи: Почерк, ЕГЭ, Видео-ссылки, Уровни сложности)
        self.system_instructions = (
            "Ты — универсальный ИИ-репетитор. Твои возможности:\n"
            "1. Анализ фото (даже плохой почерк).\n"
            "2. Решение задач по ГОСТу (Дано, Решение, Ответ).\n"
            "3. Режим ЕГЭ/ОГЭ: давай советы по оформлению для экспертов.\n"
            "4. Объясняй сложные темы простыми словами.\n"
            "5. Предлагай темы для поиска на YouTube для закрепления.\n"
            "6. Пиши формулы четко. В конце делай вывод: 'Правило, которое мы применили'."
        )
        init_db()

    def send_tg(self, method, payload):
        try:
            return self.session.post(self.tg_url + method, json=payload, timeout=30).json()
        except Exception as e:
            log(f"❌ Ошибка TG API: {e}")
            return None

    def get_main_keyboard(self):
        """Создание кнопок под сообщением (Идея: Интерфейс)"""
        return {
            "inline_keyboard": [
                [{"text": "📚 Объясни проще", "callback_data": "explain_simple"}, 
                 {"text": "📝 Как на ЕГЭ", "callback_data": "ege_style"}],
                [{"text": "🇬🇧 На английский", "callback_data": "translate_en"},
                 {"text": "🎬 Видео-урок", "callback_data": "yt_search"}]
            ]
        }

    def call_gemini(self, text, img_bytes=None, mode="standard"):
        """Запрос к ИИ с ротацией ключей"""
        # Модификация промпта в зависимости от режима
        mode_prefix = ""
        if mode == "explain_simple": mode_prefix = "ОБЪЯСНИ КАК РЕБЕНКУ: "
        elif mode == "ege_style": mode_prefix = "ОФОРМИ ПО КРИТЕРИЯМ ЕГЭ: "

        parts = [{"text": f"{self.system_instructions}\n\n{mode_prefix}ЗАДАЧА: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.5}}

        for _ in range(len(self.keys)):
            log(f"📡 Запрос ИИ (Ключ {self.current_key_idx + 1})")
            api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={self.keys[self.current_key_idx]}"
            try:
                r = self.session.post(api_url, json=payload, timeout=90)
                if r.status_code == 429:
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
                    continue
                return r.json()['candidates'][0]['content']['parts'][0]['text']
            except:
                self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
        return "❌ Лимиты всех ключей временно исчерпаны."

    def send_solution(self, chat_id, text):
        """Разбивка и отправка решения (Сохранение функции деления)"""
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        for i, part in enumerate(parts):
            msg_payload = {
                "chat_id": chat_id,
                "text": f"✨ **ЧАСТЬ {i+1}/{len(parts)}**\n\n{part}" if len(parts)>1 else part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_main_keyboard() if i == len(parts)-1 else None
            }
            self.send_tg("sendMessage", msg_payload)

    def run(self):
        log("🛰 Бот активен и готов к работе...")
        while True:
            try:
                updates = self.send_tg("getUpdates", {"offset": self.offset, "timeout": 20})
                if not updates or "result" not in updates: continue

                for upd in updates["result"]:
                    self.offset = upd["update_id"] + 1
                    
                    # Обработка нажатий на кнопки (Идея: Интерактив)
                    if "callback_query" in upd:
                        query = upd["callback_query"]
                        chat_id = query["message"]["chat"]["id"]
                        mode = query["data"]
                        self.send_tg("answerCallbackQuery", {"callback_query_id": query["id"], "text": "Обработка..."})
                        ans = self.call_gemini("Повтори прошлое решение, но в режиме: " + mode)
                        self.send_solution(chat_id, "🔄 **ОБНОВЛЕННЫЙ ВАРИАНТ:**\n\n" + ans)
                        continue

                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    chat_id = msg["chat"]["id"]

                    # Обработка Фото/Текста
                    img_data = None
                    if "photo" in msg:
                        log(f"📸 Загрузка фото от {chat_id}")
                        file_id = msg["photo"][-1]["file_id"]
                        f_info = self.send_tg("getFile", {"file_id": file_id})
                        f_path = f_info["result"]["file_path"]
                        img_raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_path}").content
                        
                        img = Image.open(io.BytesIO(img_raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    user_prompt = msg.get("text", msg.get("caption", "Реши задачу"))
                    if user_prompt == "/start":
                        self.send_tg("sendMessage", {"chat_id": chat_id, "text": "👋 Привет! Пришли фото задачи, и я решу её по всем правилам!"})
                        continue

                    self.send_tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                    solution = self.call_gemini(user_prompt, img_data)
                    self.send_solution(chat_id, solution)
                            
            except Exception as e:
                log(f"⚠️ Ошибка: {e}")
                time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    UltimateGdzBot().run()
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
