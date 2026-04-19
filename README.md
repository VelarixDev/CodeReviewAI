# 🤖 Code Review AI Bot

An AI-powered Telegram bot with a FastAPI web server that indexes GitHub repositories, analyzes code using neural networks, and answers questions about the codebase.

## ✨ Features

- 🔍 **Repository Indexing** — Load any GitHub repository into a vector database (ChromaDB)
- 💬 **RAG Chat** — Ask questions about your code and get context-aware answers
- 🌐 **GitHub Webhook** — Automatic code review on push events
- 🤖 **AI-Powered Analysis** — Uses OpenRouter API with GLM-4.5-Air model

## 📁 Project Structure

```
CodeReviewAI/
├── bot.py              # Main bot + FastAPI server (merged)
├── extractor.py        # Repository cloning, embedding & RAG logic
├── token.txt           # API tokens and credentials (4 lines)
├── ngrok.exe           # Tunnel executable for local webhook testing
└── chroma_db/          # ChromaDB vector storage (auto-created)
```

## 🛠️ Prerequisites

- Python 3.10+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- An OpenRouter API Key ([Get one here](https://openrouter.ai))
- A GitHub Personal Access Token with `repo` scope ([Create token](https://github.com/settings/tokens))

## 📦 Installation

1. **Clone or download** the project files

2. **Install dependencies:**
```bash
pip install aiogram fastapi openai uvicorn httpx chromadb gitpython tiktoken
```

3. **Configure `token.txt`** — Create this file with exactly 4 lines:
```
8673561141:AAFuWdA4Yb...                          # Telegram Bot Token
sk-or-v1-xxxxx...                                 # OpenRouter API Key
ghp_xxxxx...                                      # GitHub Personal Access Token
2403102141                                        # Chat ID for notifications
```

## 🚀 Usage

### Start the bot and server:
```bash
python bot.py
```

This launches **two services simultaneously**:
- **Telegram Bot** — Running with long-polling (polling)
- **FastAPI Web Server** — Listening on `http://0.0.0.0:8000` for GitHub webhooks

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and see instructions |
| `/analyze <URL>` | Index a GitHub repository (e.g., `/analyze https://github.com/openai/whisper`) |
| `/help` | Show help message |

### Asking Questions

After indexing a repository, simply send any text message to ask questions about the code. The bot will use RAG (Retrieval-Augmented Generation) to find relevant code snippets and generate an answer.

## 🔧 GitHub Webhook Setup

The FastAPI server exposes a POST endpoint:
```
POST /webhook/github
```

When a push event occurs on your linked GitHub repository, the webhook:
1. Receives the payload
2. Iterates through modified/added/removed files
3. Fetches file contents via GitHub API
4. Sends each file to AI for code review
5. Notifies you in Telegram with the analysis report

### Testing locally with ngrok:
```bash
# In one terminal, start your bot
python bot.py

# In another terminal, start ngrok
.\ngrok.exe http 8000

# Copy the ngrok HTTPS URL and configure it as a webhook URL in your GitHub repository settings
```

## 🏗️ Architecture

```
┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Telegram User     │────>│  Telegram Bot    │────>│  ChromaDB       │
│                     │     │  (aiogram)       │     │  (vector store) │
│  /start             │     │                  │     │                   │
│  /analyze <URL>     │     │  analyze_repo()  │<----│                   │
│  /help              │     │                  │     │                   │
│  <question text>    │     │  search_code()   │────>│                   │
└─────────────────────┘     └────────┬─────────┘     └─────────────────┘
                                     │
                                     ▼
                            ┌──────────────────┐
                            │  OpenRouter API  │
                            │  (GLM-4.5-Air)   │
                            └──────────────────┘

┌─────────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   GitHub            │────>│  FastAPI Server  │────>│  Telegram Bot   │
│   Webhook           │     │  (FastAPI)       │     │  (send_message) │
│                     │     │                  │     │                   │
│  push event         │     │  POST /webhook/  │     │  Code review      │
│                     │     │  github          │     │  notifications    │
└─────────────────────┘     └──────────────────┘     └─────────────────┘
```

## 📝 How It Works

### Repository Indexing (`extractor.py`)
1. **Clones** the GitHub repository to a temporary directory
2. **Reads** all Python files (configurable)
3. **Splits** large files into chunks using `tiktoken`
4. **Generates embeddings** via OpenRouter API
5. **Stores** everything in ChromaDB for fast retrieval

### RAG Question Answering
1. **Searches** ChromaDB for relevant code snippets matching the question
2. **Constructs** a system prompt with the retrieved context
3. **Queries** OpenRouter AI to generate an answer based on the code
4. **Returns** the answer to the user via Telegram

### Code Review Webhook
1. **Listens** for POST requests at `/webhook/github`
2. **Parses** the webhook payload for commit information
3. **Fetches** file contents from GitHub API (base64 decoded)
4. **Analyzes** each file with AI for bugs, memory leaks, and bad practices
5. **Sends** the review report to the configured Chat ID

## ⚙️ Configuration

### `token.txt` Format
```
Line 1: Telegram Bot Token       (from @BotFather)
Line 2: OpenRouter API Key        (from openrouter.ai)
Line 3: GitHub Personal Access    (with repo scope)
Line 4: Chat ID                   (your Telegram user ID)
```

### AI Model
The bot uses `z-ai/glm-4.5-air:free` via OpenRouter, which is a free tier model. You can change it in `bot.py`:
```python
model="z-ai/glm-4.5-air:free"  # Change to any OpenRouter model
```

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `token.txt not found` | Create the file with exactly 4 lines as described above |
| `Bad Request: can't parse entities` | Check that HTML messages use valid tags (`<b>`, `<i>`, `<code>`) |
| Webhook not triggering | Use ngrok to expose your local server, then set the ngrok URL in GitHub repo settings |
| AI returns empty answers | Ensure the repository was indexed successfully with `/analyze` |

## 📄 License

This project is for personal/educational use. Modify as needed for your own projects.

## 🔧 GitHub Webhook Setup (How to connect your repo)

To make the bot automatically review your code on every git push, you need to connect your GitHub repository to the bot's FastAPI server.

### Step 1: Get a public URL
If you are running the bot locally on your PC, use ngrok to expose your local server to the internet:
# In one terminal, start the bot:
python bot.py

# In a second terminal, start ngrok:
ngrok http 8000
*Copy the HTTPS URL provided by ngrok (e.g., https://1234-abcd.ngrok-free.app).*

### Step 2: Configure GitHub Webhooks
1. Go to the GitHub repository you want to monitor.
2. Navigate to Settings ➔ Webhooks (in the left sidebar).
3. Click the Add webhook button.
4. Fill in the form exactly like this:
   - Payload URL: Paste your ngrok URL and add /webhook/github at the end. 
     *(Example: https://1234-abcd.ngrok-free.app/webhook/github)*
   - Content type: Select application/json 
   - Which events would you like to trigger this webhook?: Select Just the push event.
5. Click Add webhook at the bottom.

### Step 3: Test the Automation!
Make any change in your repository, commit, and git push. 
Within seconds, the FastAPI server will catch the webhook, download the modified files, analyze them via AI, and send a detailed Code Review report directly to your Telegram DMs!