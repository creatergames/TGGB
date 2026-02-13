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

# --- ИНИЦИАЛИЗАЦИЯ ---
load_dotenv()
app = Flask('')

# Хранилище личных ключей
user_keys = {}

@app.route('/')
def home():
    # Мгновенный ответ для Health Check Render
    return "🚀 Бот онлайн. Деплой успешен!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    # Передача host='0.0.0.0' критична для Render
    app.run(host='0.0.0.0', port=port)

def log(message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}")

# --- КЛАСС БОТА (БЕЗ ОШИБОК ОТСТУПОВ) ---
class UltraGdzBot:
    def __init__(self):
        log("⚙️ Сборка системы...")
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        self.admin_key = os.getenv("GEMINI_API_KEY") 
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-2.0-flash" 
        self.offset = 0
        self.session = requests.Session()
        
        self.system_instructions = (
            "Ты — элитный ИИ-репетитор. Решай всё по фото.\n"
            "Формат: **Дано**, **Решение**, **Ответ**.\n"
            "Добавляй советы для ЕГЭ и YouTube темы."
        )

    def get_keyboard(self):
        return {
            "inline_keyboard": [
                [{"text": "📚 Проще", "callback_data": "mode_simple"}, 
                 {"text": "📝 ЕГЭ", "callback_data": "mode_ege"}],
                [{"text": "🔑 Свой ключ", "callback_data": "tutorial"}]
            ]
        }

    def call_ai(self, text, img_bytes=None, user_id=None, sub_mode="standard"):
        active_key = user_keys.get(user_id, self.admin_key)
        
        instruction = self.system_instructions
        if sub_mode == "mode_simple": instruction += "\nУпрости объяснение."
        elif sub_mode == "mode_ege": instruction += "\nОформи по критериям ЕГЭ."

        parts = [{"text": f"{instruction}\n\nЗАДАЧА: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.3}}
        api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={active_key}"

        try:
            r = self.session.post(api_url, json=payload, timeout=90)
            if r.status_code == 429: return "LIMIT_ERROR"
            return r.json()['candidates'][0]['content']['parts'][0]['text']
        except:
            return "ERROR"

    def send_smart_msg(self, chat_id, text, with_kb=True):
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            payload = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_keyboard() if (is_last and with_kb) else None
            }
            try:
                self.session.post(self.tg_url + "sendMessage", json=payload)
            except:
                payload.pop("parse_mode", None)
                self.session.post(self.tg_url + "sendMessage", json=payload)

    def run(self):
        log("🛰 Бот активен...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}).json()
                for upd in r.get("result", []):
                    self.offset = upd["update_id"] + 1
                    
                    if "callback_query" in upd:
                        cb = upd["callback_query"]
                        uid = cb["message"]["chat"]["id"]
                        self.session.post(self.tg_url + "answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        
                        if cb["data"] == "tutorial":
                            self.send_smart_msg(uid, "🔑 Пришли свой API Key от Google AI Studio.", with_kb=False)
                        else:
                            res = self.call_ai("Обнови решение", user_id=uid, sub_mode=cb["data"])
                            self.send_smart_msg(uid, "🔄 **ОБНОВЛЕНИЕ:**\n\n" + res)
                        continue

                    msg = upd.get("message")
                    if not msg: continue
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    if text == "/start":
                        self.send_smart_msg(chat_id, "👋 Привет! Пришли фото задачи.", with_kb=False)
                        continue

                    if text.strip().startswith("AIza"):
                        user_keys[chat_id] = text.strip()
                        self.send_smart_msg(chat_id, "✅ Ключ привязан!", with_kb=False)
                        continue

                    img_data = None
                    if "photo" in msg:
                        fid = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": fid}).json()
                        raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        img = Image.open(io.BytesIO(raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    prmpt = msg.get("text", msg.get("caption", "Реши задачу"))
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                    ans = self.call_ai(prmpt, img_data, user_id=chat_id)

                    if ans == "LIMIT_ERROR":
                        self.send_smart_msg(chat_id, "⚠️ Лимиты исчерпаны. Добавь свой ключ!", with_kb=True)
                    elif ans == "ERROR":
                        self.send_smart_msg(chat_id, "❌ Ошибка. Попробуй еще раз.", with_kb=False)
                    else:
                        self.send_smart_msg(chat_id, ans)

            except Exception as e:
                log(f"🛑 Ошибка: {e}")
                time.sleep(5)

# --- ЗАПУСК ---
if __name__ == "__main__":
    # Сначала запускаем веб-сервер, чтобы Render увидел активный порт
    Thread(target=run_web, daemon=True).start()
    # Затем запускаем основного бота
    UltraGdzBot().run()
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-2.0-flash" 
        self.offset = 0
        self.session = requests.Session()
        
        # Системные инструкции (10 идей развития)
        self.system_instructions = (
            "Ты — элитный ИИ-репетитор. Твои правила:\n"
            "1. Решай всё по фото (текст, формулы, почерк).\n"
            "2. Формат: **Дано**, **Решение**, **Ответ**.\n"
            "3. Режим ЕГЭ: давай советы по правилам оформления.\n"
            "4. В конце добавь: '🎥 Рекомендую темы для YouTube: [Темы]'.\n"
            "5. Используй LaTeX и Markdown для четкости.\n"
            "6. Объясняй шаги так, чтобы понял даже слабый ученик."
        )

    def get_keyboard(self):
        """Интерактивное меню"""
        return {
            "inline_keyboard": [
                [{"text": "📚 Объясни проще", "callback_data": "mode_simple"}, 
                 {"text": "📝 Режим ЕГЭ/ОГЭ", "callback_data": "mode_ege"}],
                [{"text": "🔑 Свой ключ (Инструкция)", "callback_data": "tutorial"},
                 {"text": "🇬🇧 На английский", "callback_data": "mode_en"}]
            ]
        }

    def call_ai(self, text, img_bytes=None, user_id=None, sub_mode="standard"):
        """Запрос к ИИ с поддержкой BYOK"""
        active_key = user_keys.get(user_id, self.admin_key)
        
        instruction = self.system_instructions
        if sub_mode == "mode_simple": instruction += "\nУпрости объяснение до максимума."
        elif sub_mode == "mode_ege": instruction += "\nСделай акцент на оформлении для ЕГЭ/ОГЭ."
        elif sub_mode == "mode_en": instruction += "\nПереведи решение на английский язык."

        parts = [{"text": f"{instruction}\n\nЗАДАЧА: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.3}}
        api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={active_key}"

        try:
            r = self.session.post(api_url, json=payload, timeout=90)
            if r.status_code == 429: return "LIMIT_ERROR"
            if r.status_code != 200: return "ERROR"
            return r.json()['candidates'][0]['content']['parts'][0]['text']
        except:
            return "ERROR"

    def send_smart_msg(self, chat_id, text, with_kb=True):
        """Деление длинных сообщений и отправка"""
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            payload = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_keyboard() if (is_last and with_kb) else None
            }
            try:
                self.session.post(self.tg_url + "sendMessage", json=payload)
            except:
                payload.pop("parse_mode", None)
                self.session.post(self.tg_url + "sendMessage", json=payload)

    def run(self):
        log("🛰 [SYS] Бот запущен и слушает...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}).json()
                for upd in r.get("result", []):
                    self.offset = upd["update_id"] + 1
                    
                    if "callback_query" in upd:
                        cb = upd["callback_query"]
                        uid = cb["message"]["chat"]["id"]
                        self.session.post(self.tg_url + "answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        
                        if cb["data"] == "tutorial":
                            t_msg = ("🔑 **ИНСТРУКЦИЯ ПО КЛЮЧУ**\n\n"
                                     "1. Зайди на [Google AI Studio](https://aistudio.google.com/app/apikey)\n"
                                     "2. Создай бесплатный API Key.\n"
                                     "3. Просто **пришли его мне** сообщением.\n\n"
                                     "Это снимет любые лимиты!")
                            self.send_smart_msg(uid, t_msg, with_kb=False)
                        else:
                            res = self.call_ai("Обнови решение", user_id=uid, sub_mode=cb["data"])
                            self.send_smart_msg(uid, "🔄 **ОБНОВЛЕНИЕ:**\n\n" + res)
                        continue

                    msg = upd.get("message")
                    if not msg: continue
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    if text == "/start":
                        welcome = ("👋 **Привет! Я твой личный ГДЗ-помощник.**\n\n"
                                   "Я использую **Gemini 2.5 Flash**, чтобы решать задачи по фото.\n"
                                   "📸 Просто пришли мне фото или напиши условие.")
                        self.send_smart_msg(chat_id, welcome, with_kb=False)
                        continue

                    if text.strip().startswith("AIza"):
                        user_keys[chat_id] = text.strip()
                        self.send_smart_msg(chat_id, "✅ **Ключ привязан!** Теперь я работаю на твоих лимитах.", with_kb=False)
                        continue

                    img_data = None
                    if "photo" in msg:
                        log(f"📸 Фото от {chat_id}")
                        fid = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": fid}).json()
                        raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        img = Image.open(io.BytesIO(raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    prompt = msg.get("text", msg.get("caption", "Реши задачу"))
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                    
                    ans = self.call_ai(prompt, img_data, user_id=chat_id)

                    if ans == "LIMIT_ERROR":
                        err = "⚠️ **Лимиты бота исчерпаны.**\nДобавь свой бесплатный ключ по кнопке ниже!"
                        self.send_smart_msg(chat_id, err, with_kb=True)
                    elif ans == "ERROR":
                        self.send_smart_msg(chat_id, "❌ Ошибка. Попробуй другое фото.", with_kb=False)
                    else:
                        self.send_smart_msg(chat_id, ans)

            except Exception as e:
                log(f"🛑 [LOOP ERROR] {e}")
                time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    UltraGdzBot().run()
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        # Самая мощная модель для 2026 года
        self.model_name = "models/gemini-2.0-flash" 
        self.offset = 0
        self.session = requests.Session()
        
        # 10 идей внедрены в этот промпт
        self.system_instructions = (
            "Ты — элитный ИИ-репетитор. Твои правила:\n"
            "1. Решай всё по фото (текст, формулы, почерк).\n"
            "2. Формат: **Дано**, **Решение**, **Ответ**.\n"
            "3. Режим ЕГЭ: давай подсказки по правильному оформлению.\n"
            "4. В конце пиши '🎥 Рекомендую темы для YouTube: ...' (идея №8).\n"
            "5. Используй LaTeX символы и жирный шрифт для scannability.\n"
            "6. Объясняй логику решения максимально понятно."
        )

    def get_main_keyboard(self):
        """Интерактивное меню под сообщениями"""
        return {
            "inline_keyboard": [
                [{"text": "📚 Объясни проще", "callback_data": "mode_simple"}, 
                 {"text": "📝 Режим ЕГЭ/ОГЭ", "callback_data": "mode_ege"}],
                [{"text": "🔑 Добавить свой ключ", "callback_data": "tutorial"},
                 {"text": "🇬🇧 На английский", "callback_data": "mode_en"}]
            ]
        }

    def call_gemini_ai(self, text, img_bytes=None, user_id=None, sub_mode="standard"):
        """Ядро ИИ с поддержкой личных ключей и ротации"""
        # Используем личный ключ юзера или основной админский
        active_key = user_keys.get(user_id, self.admin_key)
        
        instruction = self.system_instructions
        if sub_mode == "mode_simple": instruction += "\nМаксимально упрости объяснение."
        elif sub_mode == "mode_ege": instruction += "\nОформи строго по критериям госэкзаменов."
        elif sub_mode == "mode_en": instruction += "\nПереведи всё решение на английский язык."

        parts = [{"text": f"{instruction}\n\nЗАДАЧА: {text}"}]
        if img_bytes:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.3}}
        api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={active_key}"

        try:
            r = self.session.post(api_url, json=payload, timeout=90)
            if r.status_code == 429:
                return "LIMIT_ERROR"
            if r.status_code != 200:
                return "ERROR"
            return r.json()['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            log(f"🛑 [AI ERROR] {e}")
            return "ERROR"

    def send_smart_message(self, chat_id, text, with_kb=True):
        """Разбивка длинных сообщений (идея №7) и отправка"""
        limit = 3800
        text_parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        
        for i, part in enumerate(text_parts):
            is_last_part = (i == len(text_parts) - 1)
            payload = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_main_keyboard() if (is_last_part and with_kb) else None
            }
            try:
                self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)
            except:
                # Если Markdown вызвал ошибку, шлем чистым текстом
                payload.pop("parse_mode", None)
                self.session.post(self.tg_url + "sendMessage", json=payload, timeout=30)

    def run_polling(self):
        log("🛰 [READY] Бот начал опрос Telegram...")
        while True:
            try:
                res = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}).json()
                for upd in res.get("result", []):
                    self.offset = upd["update_id"] + 1
                    
                    # 1. ОБРАБОТКА КНОПОК
                    if "callback_query" in upd:
                        cq = upd["callback_query"]
                        uid = cq["message"]["chat"]["id"]
                        self.session.post(self.tg_url + "answerCallbackQuery", json={"callback_query_id": cq["id"]})
                        
                        if cq["data"] == "tutorial":
                            t_msg = ("🔑 **ИНСТРУКЦИЯ ПО КЛЮЧУ**\n\n"
                                     "1. Зайди на [Google AI Studio](https://aistudio.google.com/app/apikey)\n"
                                     "2. Нажми **'Create API key'**\n"
                                     "3. Пришли скопированный ключ мне (начинается на AIza).\n\n"
                                     "Это даст тебе **полный безлимит**!")
                            self.send_smart_message(uid, t_msg, with_kb=False)
                        else:
                            log(f"🔘 Кнопка: {cq['data']} от {uid}")
                            new_ans = self.call_gemini_ai("Переработай ответ в этом режиме", user_id=uid, sub_mode=cq["data"])
                            self.send_smart_message(uid, "🔄 **ОБНОВЛЕННОЕ РЕШЕНИЕ:**\n\n" + new_ans)
                        continue

                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    chat_id = msg["chat"]["id"]
                    u_text = msg.get("text", "")

                    # 2. ПРИВЕТСТВИЕ (Идея №2)
                    if u_text == "/start":
                        welcome = ("👋 **Привет! Я твой элитный ГДЗ-бот 2026.**\n\n"
                                   "📸 Просто пришли мне **фото задачи** или напиши её текстом.\n\n"
                                   "✨ Я умею:\n"
                                   "• Решать математику, физику, химию\n"
                                   "• Разбирать рукописный почерк\n"
                                   "• Объяснять сложные темы\n"
                                   "• Давать советы для ЕГЭ")
                        self.send_smart_message(chat_id, welcome, with_kb=False)
                        continue

                    # 3. ПРИЕМ ЛИЧНОГО КЛЮЧА
                    if u_text.strip().startswith("AIza"):
                        user_keys[chat_id] = u_text.strip()
                        log(f"🔑 Пользователь {chat_id} добавил свой ключ.")
                        self.send_smart_message(chat_id, "✅ **Ключ принят!** Теперь для тебя действуют твои персональные лимиты.", with_kb=False)
                        continue

                    # 4. ОБРАБОТКА ФОТО (Идея №10 - сжатие)
                    img_data = None
                    if "photo" in msg:
                        log(f"📸 Фото от {chat_id}")
                        fid = msg["photo"][-1]["file_id"]
                        fpath = self.session.get(self.tg_url + "getFile", params={"file_id": fid}).json()["result"]["file_path"]
                        raw_img = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{fpath}").content
                        
                        img = Image.open(io.BytesIO(raw_img)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    # 5. ГЕНЕРАЦИЯ ОТВЕТА
                    prompt = msg.get("text", msg.get("caption", "Реши задачу на фото"))
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                    
                    ans = self.call_gemini_ai(prompt, img_data, user_id=chat_id)

                    # 6. ВЫХОД ПРИ ЗАКОНЧИВШИХСЯ ЛИМИТАХ
                    if ans == "LIMIT_ERROR":
                        l_msg = ("⚠️ **Лимиты бота исчерпаны!**\n\n"
                                 "Сегодня было слишком много задач. Чтобы продолжить прямо сейчас, "
                                 "добавь **свой личный ключ** (это бесплатно). Нажми кнопку ниже для инструкции.")
                        self.send_smart_message(chat_id, l_msg, with_kb=True)
                    elif ans == "ERROR":
                        self.send_smart_message(chat_id, "❌ Ошибка. Попробуй другое фото.", with_kb=False)
                    else:
                        self.send_smart_message(chat_id, ans)

            except Exception as e:
                log(f"🛑 [CRITICAL] {e}")
                time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    UltraMasterBot().run_polling()
        self.tg_url = f"https://api.telegram.org/bot{self.tg_token}/"
        self.model_name = "models/gemini-2.0-flash" 
        self.offset = 0
        self.session = requests.Session()
        
        self.system_instructions = (
            "Ты — элитный ИИ-репетитор. Твои правила:\n"
            "1. Решай всё по фото (даже рукописное).\n"
            "2. Формат: **Дано**, **Решение**, **Ответ**.\n"
            "3. Режим ЕГЭ: давай советы по оформлению.\n"
            "4. В конце пиши '🎥 Темы для YouTube: ...'.\n"
            "5. Используй LaTeX и объясняй логику просто."
        )

    def get_kb(self):
        """Инлайн-кнопки для меню"""
        return {
            "inline_keyboard": [
                [{"text": "📚 Объясни проще", "callback_data": "mode_simple"}, 
                 {"text": "📝 Режим ЕГЭ/ОГЭ", "callback_data": "mode_ege"}],
                [{"text": "🔑 Свой ключ (Инструкция)", "callback_data": "tutorial"}]
            ]
        }

    def call_ai(self, text, img_bytes=None, user_id=None, sub_mode="standard"):
        """Запрос к нейросети с учетом личных ключей"""
        # Проверка: есть ли у юзера свой ключ, если нет - берем админский
        active_key = user_keys.get(user_id, self.admin_key)
        
        instruction = self.system_instructions
        if sub_mode == "mode_simple": instruction += "\nУпрости объяснение."
        elif sub_mode == "mode_ege": instruction += "\nОформи по критериям ЕГЭ."

        parts = [{"text": f"{instruction}\n\nЗАДАЧА: {text}"}]
        if img_bytes:
            log(f"🖼 [AI] Обработка фото для {user_id}")
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img_bytes).decode()}})
        
        payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.35}}
        api_url = f"https://generativelanguage.googleapis.com/v1/{self.model_name}:generateContent?key={active_key}"

        try:
            r = self.session.post(api_url, json=payload, timeout=90)
            if r.status_code == 429:
                log(f"⏳ [LIMIT] Лимит исчерпан для {user_id}")
                return "LIMIT_ERROR"
            if r.status_code != 200:
                log(f"❌ [AI ERROR] {r.text}")
                return "ERROR"
            return r.json()['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            log(f"🛑 [CRIT] {e}")
            return "ERROR"

    def send_final(self, chat_id, text, use_kb=True):
        """Отправка с разбивкой длинных текстов"""
        limit = 3800
        parts = [text[i:i + limit] for i in range(0, len(text), limit)]
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            payload = {
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "reply_markup": self.get_kb() if (is_last and use_kb) else None
            }
            self.session.post(self.tg_url + "sendMessage", json=payload)

    def run(self):
        log("🛰 [SYS] Бот в эфире...")
        while True:
            try:
                r = self.session.get(self.tg_url + "getUpdates", params={"offset": self.offset, "timeout": 20}).json()
                for upd in r.get("result", []):
                    self.offset = upd["update_id"] + 1
                    
                    # Обработка кнопок
                    if "callback_query" in upd:
                        cb = upd["callback_query"]
                        chat_id = cb["message"]["chat"]["id"]
                        self.session.post(self.tg_url + "answerCallbackQuery", json={"callback_query_id": cb["id"]})
                        
                        if cb["data"] == "tutorial":
                            msg = ("🔑 **КАК ДОБАВИТЬ СВОЙ КЛЮЧ?**\n\n"
                                   "1. Зайди на [Google AI Studio](https://aistudio.google.com/app/apikey)\n"
                                   "2. Нажми **'Create API key'**\n"
                                   "3. Скопируй его (начинается на AIza...)\n"
                                   "4. Просто **пришли его мне в чат** сообщением.\n\n"
                                   "Это бесплатно и снимет все лимиты!")
                            self.send_final(chat_id, msg, use_kb=False)
                        else:
                            log(f"🔘 [BTN] Режим {cb['data']} для {chat_id}")
                            res = self.call_ai("Обнови решение", user_id=chat_id, sub_mode=cb["data"])
                            self.send_final(chat_id, "🔄 **РЕЗУЛЬТАТ ОБРАБОТКИ:**\n\n" + res)
                        continue

                    msg = upd.get("message")
                    if not msg or "chat" not in msg: continue
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text", "")

                    # Если пользователь прислал API-ключ
                    if text.strip().startswith("AIza"):
                        user_keys[chat_id] = text.strip()
                        log(f"🔑 [KEY] Пользователь {chat_id} добавил свой ключ.")
                        self.send_final(chat_id, "✅ **Ключ успешно подключен!** Теперь ты на безлимите.", use_kb=False)
                        continue

                    if text == "/start":
                        self.send_final(chat_id, "📚 Привет! Пришли фото задачи. Если лимиты закончатся, ты сможешь добавить свой ключ.", use_kb=False)
                        continue

                    img_data = None
                    if "photo" in msg:
                        log(f"📸 [FILE] Загрузка фото от {chat_id}")
                        f_id = msg["photo"][-1]["file_id"]
                        f_info = self.session.get(self.tg_url + "getFile", params={"file_id": f_id}).json()
                        raw = self.session.get(f"https://api.telegram.org/file/bot{self.tg_token}/{f_info['result']['file_path']}").content
                        img = Image.open(io.BytesIO(raw)).convert('RGB')
                        img.thumbnail((1600, 1600))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=85)
                        img_data = buf.getvalue()

                    prmpt = msg.get("text", msg.get("caption", "Реши задачу"))
                    self.session.post(self.tg_url + "sendChatAction", json={"chat_id": chat_id, "action": "typing"})
                    
                    ans = self.call_ai(prmpt, img_data, user_id=chat_id)

                    if ans == "LIMIT_ERROR":
                        err = ("⚠️ **Общие лимиты бота исчерпаны!**\n\n"
                               "Чтобы продолжить прямо сейчас, добавь свой личный ключ по кнопке ниже.")
                        self.send_final(chat_id, err, use_kb=True)
                    elif ans == "ERROR":
                        self.send_final(chat_id, "❌ Произошла ошибка. Попробуй еще раз.", use_kb=False)
                    else:
                        self.send_final(chat_id, ans)

            except Exception as e:
                log(f"🛑 [LOOP ERR] {e}")
                time.sleep(5)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    UltimateGdzBot().run()
