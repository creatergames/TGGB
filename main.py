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

# Словарь для хранения личных ключей пользователей (user_id: api_key)
user_keys = {}

@app.route('/')
def home():
    return "🚀 Бот ГДЗ 2026: Работаю стабильно | BYOK Mode"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def log(message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {message}")

# --- КЛАСС БОТА ---
class UltimateGdzBot:
    def __init__(self):
        log("⚙️ [INIT] Сборка без ошибок отступов...")
        self.tg_token = os.getenv("TELEGRAM_TOKEN")
        self.admin_key = os.getenv("GEMINI_API_KEY") 
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
