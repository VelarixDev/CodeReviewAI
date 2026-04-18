import asyncio
import logging
import base64
import httpx
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandObject, Command
from fastapi import FastAPI, Request
from openai import AsyncOpenAI
import uvicorn

# Настройка логирования для бота
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Импортируем функции из экстрактора кода (должен быть в той же папке)
try:
    from extractor import analyze_repo, search_code
except ImportError as e:
    raise ImportError("Не удалось импортировать модуль 'extractor'. Убедитесь, что файл 'extractor.py' находится в текущей директории.") from e

# Загрузка токенов из файла token.txt
def load_keys() -> tuple[str, str, int, str]:
    try:
        with open("token.txt", "r") as f:
            lines = [line.strip() for line in f if line.strip()]
            if len(lines) < 4:
                raise ValueError("Файл token.txt должен содержать как минимум четыре строки:\n"
                                 "1. Telegram Bot Token\n"
                                 "2. OpenRouter API Key\n"
                                 "3. GitHub Token\n"
                                 "4. Chat ID для уведомлений")
            return lines[0], lines[1], lines[2], int(lines[3])
    except FileNotFoundError:
        print("\n❌ Ошибка: Файл 'token.txt' не найден!")
        exit(1)
    except Exception as e:
        print(f"\n❌ Произошла ошибка при загрузке keys из token.txt: {e}")
        exit(1)

BOT_TOKEN, OPENROUTER_API_KEY, GH_TOKEN, CHAT_ID = load_keys()

# Глобальные объекты в начале файла
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
app = FastAPI()


async def analyze_code_with_ai(file_content, filename):
    """Анализ кода с помощью ИИ."""
    prompt = f"Проверь этот файл {filename} на ошибки, утечки памяти или плохой код. Напиши краткий отчет:\n\n{file_content[:3000]}"
    response = await client.chat.completions.create(
        model="z-ai/glm-4.5-air:free",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


# ==================== Telegram Bot Handlers ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветствие при команде /start."""
    await message.answer(
        "🚀 <b>Code Review AI Bot</b>\n\n"
        "Я могу проиндексировать ваш код и отвечать на вопросы по нему.\n\n"
        "🔹 Чтобы индексировать репозиторий, отправьте:\n"
        "<code>/analyze URL</code> (например: <code>/analyze https://github.com/openai/whisper</code>)\n\n"
        "🔹 После завершения задавайте любые вопросы текстом — я отвечу на основе кода.\n\n"
        "<i>Используйте /help для справки</i>", parse_mode="HTML", reply_markup=None
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Справка по командам."""
    await message.answer(
        "<b>📝 Команды:</b>\n\n"
        "- <code>/analyze https://github.com/user/repo</code> — проиндексировать репозиторий\n"
        "- Отправьте текст вопроса — получить ответ на основе кода\n\n"
        "<i>Примечание: Индексация может занять до 1-2 минут</i>",
        parse_mode="HTML"
    )


@dp.message(Command("analyze"))
async def cmd_analyze(message: types.Message, command: CommandObject):
    """Обработчик команды /analyze <url>."""
    if not command.args or not command.args.strip():
        await message.answer(
            "⚠️ Вы забыли указать ссылку!\n\n"
            "Используйте формат:\n"
            "<code>/analyze https://github.com/user/repo</code>",
            parse_mode="HTML"
        )
        return

    url = command.args.strip()

    if not url.startswith("https://github.com/"):
        await message.answer(
            "❌ Некорректная ссылка.\n"
            "Пожалуйста, введите ссылку на GitHub, начинающуюся с <code>https://github.com/</code>",
            parse_mode="HTML"
        )
        return
    status_msg = await message.answer(f"⏳ <b>Загружаю и анализирую репозиторий...</b>\n<code>{url}</code>", parse_mode="HTML")

    try:
        await asyncio.to_thread(analyze_repo, url)
        await status_msg.edit_text("✅ Репозиторий проиндексирован! Задавайте вопросы по коду.", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Ошибка при индексации репозитория {url}: {e}")
        await status_msg.edit_text("❌ Ошибка при обработке URL.\n\nПроверьте ссылку или попробуйте позже.", parse_mode="HTML")


@dp.message()
async def handle_question(message: types.Message):
    """Основной хэндлер вопросов (RAG)."""
    if not message.text or len(message.text) < 5:
        return

    status_msg = await message.answer("⏳ Думаю...", parse_mode="HTML")

    try:
        context_chunks = await asyncio.to_thread(search_code, query=message.text)

        if not context_chunks or "База данных кода не найдена" in context_chunks:
            await status_msg.edit_text("❌ Репозиторий еще не проиндексирован.\nСначала используйте <code>/analyze <URL></code>", parse_mode="HTML")
            return

        system_prompt = (
            "Ты — Senior Developer. Твоя задача: отвечать на вопросы пользователя, используя ТОЛЬКО нижеприведенный фрагменты кода.\n\n"
            f"{context_chunks}\n\n"
            "Инструкции:\n"
            "1. Отвечай кратко и точно (2-4 предложения).\n"
            "2. Если в предоставленном контексте нет ответа, скажи: 'Извините, я не нашел информацию о данном вопросе в текущем индексе кода.'\n"
            "3. Не выдумывай ничего, чего нет в коде.\n"
            "4. Используй технический тон."
        )

        response = await client.chat.completions.create(
            model="z-ai/glm-4.5-air:free",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message.text}
            ],
            extra_headers={
                "HTTP-Referer": "https://github.com/codeReviewAIBot",
                "X-Title": "Code Review AI Bot",
            },
            timeout=45
        )

        answer = response.choices[0].message.content if response else "🤖 Модель вернула пустой ответ."
        await status_msg.edit_text(answer)

    except Exception as e:
        logger.error(f"Ошибка RAG-поиска для сообщения {message.from_user.id}: {e}")
        await status_msg.edit_text("❌ Ошибка при получении ответа от нейросети.\nПопробуйте еще раз позже.", parse_mode="HTML")


# ==================== FastAPI Webhook Endpoint ====================

@app.post("/webhook/github")
async def github_webhook(request: Request):
    """POST /webhook/github - принимает webhook от GitHub."""
    payload = await request.json()

    if 'commits' in payload:
        for commit in payload['commits']:
            modified_files = commit.get('modified', [])
            added_files = commit.get('added', [])
            removed_files = commit.get('removed', [])
            all_files = modified_files + added_files + removed_files

            for file_path in all_files:
                headers = {"Authorization": f"token {GH_TOKEN}"}
                repo_name = payload['repository']['full_name']
                raw_url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"

                async with httpx.AsyncClient() as http:
                    resp = await http.get(raw_url, headers=headers)
                    if resp.status_code == 200:
                        content = resp.json()['content']
                        decoded_code = base64.b64decode(content).decode('utf-8')

                        ai_report = await analyze_code_with_ai(decoded_code, file_path)

                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=f"🔍 Code Review: {file_path}\n\n{ai_report}"
                        )

    return {"status": "ok"}


# ==================== Main Entry Point ====================

async def start_webhook_server():
    """Запуск веб-сервера FastAPI через Uvicorn."""
    config = uvicorn.Config(app, host='0.0.0.0', port=8000)
    server = uvicorn.Server(config)
    await server.serve()


async def start_telegram_bot():
    """Запуск Telegram-бота."""
    print("\n🤖 Бот запущен и готов к работе!")
    print("⚙️  Веб-сервер запущен на http://0.0.0.0:8000")
    await dp.start_polling(bot, skip_updates=True)


async def main():
    """Запуск бота и веб-сервера одновременно."""
    # Установка меню команд
    await bot.set_my_commands([
        types.BotCommand(command='start', description='Запустить'),
        types.BotCommand(command='analyze', description='Анализ репозитория'),
        types.BotCommand(command='help', description='Помощь'),
    ])

    await asyncio.gather(
        start_telegram_bot(),
        start_webhook_server()
    )


if __name__ == "__main__":
    asyncio.run(main())