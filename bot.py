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

# Logging configuration for the bot
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import code extractor functions (must be in the same directory)
try:
    from extractor import analyze_repo, search_code
except ImportError as e:
    raise ImportError("Failed to import module 'extractor'. Ensure that 'extractor.py' is in the current directory.") from e

# Load tokens from token.txt file
def load_keys() -> tuple[str, str, int, str]:
    try:
        with open("token.txt", "r") as f:
            lines = [line.strip() for line in f if line.strip()]
            if len(lines) < 4:
                raise ValueError("The token.txt file must contain at least four lines:\n"
                                 "1. Telegram Bot Token\n"
                                 "2. OpenRouter API Key\n"
                                 "3. GitHub Token\n"
                                 "4. Chat ID for notifications")
            return lines[0], lines[1], lines[2], int(lines[3])
    except FileNotFoundError:
        print("\n❌ Error: 'token.txt' file not found!")
        exit(1)
    except Exception as e:
        print(f"\n❌ Error loading keys from token.txt: {e}")
        exit(1)

BOT_TOKEN, OPENROUTER_API_KEY, GH_TOKEN, CHAT_ID = load_keys()

# Global objects at the beginning of the file
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
app = FastAPI()


async def analyze_code_with_ai(file_content, filename):
    """AI-powered code analysis."""
    prompt = f"Review this file {filename} for errors, memory leaks, or poor code quality. Provide a brief report:\n\n{file_content[:3000]}"
    response = await client.chat.completions.create(
        model="z-ai/glm-4.5-air:free",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


# ==================== Telegram Bot Handlers ====================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Greeting message for /start command."""
    await message.answer(
        "🚀 <b>Code Review AI Bot</b>\n\n"
        "I can index your codebase and answer questions about it.\n\n"
        "🔹 To index a repository, send:\n"
        "<code>/analyze URL</code> (e.g., <code>/analyze https://github.com/openai/whisper</code>)\n\n"
        "🔹 Once indexing is complete, ask any questions via text — I'll respond based on your code.\n\n"
        "<i>Use /help for assistance</i>", parse_mode="HTML", reply_markup=None
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Command help message."""
    await message.answer(
        "<b>📝 Commands:</b>\n\n"
        "- <code>/analyze https://github.com/user/repo</code> — Index a repository\n"
        "- Send a question as text — Get an answer based on the codebase\n\n"
        "<i>Note: Indexing may take 1-2 minutes</i>",
        parse_mode="HTML"
    )


@dp.message(Command("analyze"))
async def cmd_analyze(message: types.Message, command: CommandObject):
    """Handler for /analyze <url> command."""
    if not command.args or not command.args.strip():
        await message.answer(
            "⚠️ You forgot to provide a URL!\n\n"
            "Use the format:\n"
            "<code>/analyze https://github.com/user/repo</code>",
            parse_mode="HTML"
        )
        return

    url = command.args.strip()

    if not url.startswith("https://github.com/"):
        await message.answer(
            "❌ Invalid URL.\n"
            "Please provide a GitHub link starting with <code>https://github.com/</code>",
            parse_mode="HTML"
        )
        return
    status_msg = await message.answer(f"⏳ <b>Loading and analyzing repository...</b>\n<code>{url}</code>", parse_mode="HTML")

    try:
        await asyncio.to_thread(analyze_repo, url)
        await status_msg.edit_text("✅ Repository indexed successfully! Ask your questions about the code.", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error indexing repository {url}: {e}")
        await status_msg.edit_text("❌ Error processing URL.\n\nPlease check the link or try again later.", parse_mode="HTML")


@dp.message()
async def handle_question(message: types.Message):
    """Main question handler (RAG)."""
    if not message.text or len(message.text) < 5:
        return

    status_msg = await message.answer("⏳ Thinking...", parse_mode="HTML")

    try:
        context_chunks = await asyncio.to_thread(search_code, query=message.text)

        if not context_chunks or "Code database not found" in context_chunks:
            await status_msg.edit_text("❌ Repository has not been indexed yet.\nPlease use <code>/analyze <URL></code> first.", parse_mode="HTML")
            return

        system_prompt = (
            "You are a Senior Developer. Your task is to answer user questions using ONLY the code snippets below.\n\n"
            f"{context_chunks}\n\n"
            "Instructions:\n"
            "1. Answer concisely and accurately (2-4 sentences).\n"
            "2. If the provided context doesn't contain an answer, say: 'Sorry, I couldn't find information about this question in the current code index.'\n"
            "3. Do not invent anything not present in the code.\n"
            "4. Maintain a technical tone."
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

        answer = response.choices[0].message.content if response else "🤖 Model returned an empty response."
        await status_msg.edit_text(answer)

    except Exception as e:
        logger.error(f"RAG search error for message from {message.from_user.id}: {e}")
        await status_msg.edit_text("❌ Error obtaining response from the AI model.\nPlease try again later.", parse_mode="HTML")


# ==================== FastAPI Webhook Endpoint ====================

@app.post("/webhook/github")
async def github_webhook(request: Request):
    """POST /webhook/github - receives webhook from GitHub."""
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
    """Start the FastAPI web server via Uvicorn."""
    config = uvicorn.Config(app, host='0.0.0.0', port=8000)
    server = uvicorn.Server(config)
    await server.serve()


async def start_telegram_bot():
    """Start the Telegram bot."""
    print("\n🤖 Bot started and ready to work!")
    print("⚙️  Web server running at http://0.0.0.0:8000")
    await dp.start_polling(bot, skip_updates=True)


async def main():
    """Start both the bot and web server simultaneously."""
    # Set command menu
    await bot.set_my_commands([
        types.BotCommand(command='start', description='Launch'),
        types.BotCommand(command='analyze', description='Repository analysis'),
        types.BotCommand(command='help', description='Help'),
    ])

    await asyncio.gather(
        start_telegram_bot(),
        start_webhook_server()
    )


if __name__ == "__main__":
    asyncio.run(main())