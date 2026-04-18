# 🌟 Magical Storybook Generator 🌟

A delightful Flask app that generates custom illustrated bedtime stories for kids aged 3+. Walk through a simple wizard — pick a character, a place, and a favourite colour — and get a unique AI-written story with a matching illustration!

## ✨ Features

- **Kid-friendly multi-step wizard** — Big buttons and emoji guide children through three simple choices (character → place → colour)
- **AI Story Generation** — Uses [Ollama](https://ollama.ai) (local LLM) to write a gentle, calming bedtime story
- **AI Illustration** — [Pollinations.ai](https://pollinations.ai) generates a matching image; it is downloaded and stored locally so stories are always viewable offline
- **Story History** — Browse all previously generated stories on the `/previous-stories` page
- **Read-Aloud** — Browser Web Speech API reads the story aloud to kids
- **Password Protection** — Optionally lock the app with a password (great for shared/family servers)
- **Customisable Prompt** — Edit the story-generation prompt directly in the Settings UI
- **Persistent Storage** — Stories and settings are stored in a local SQLite database (`instance/storytime.db`)
- **Systemd / Gunicorn deployment** — Production-ready service file included in `deploy/`

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- [Ollama](https://ollama.ai) installed and running locally

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Pull an Ollama Model

Make sure Ollama is running, then pull the default model (or any model you prefer):

```bash
# Default (fast, good quality)
ollama pull gemma2:2b

# Alternatives
ollama pull llama2
ollama pull mistral
ollama pull neural-chat
```

Start the Ollama server if it isn't running:

```bash
ollama serve
```

### 3. Run the Flask App

```bash
python app.py
```

You should see:

```
🎉 Storybook Generator starting...
📡 Ollama Host: http://localhost:11434
🤖 Ollama Model: gemma2:2b
💾 Database: /path/to/instance/storytime.db
Visit http://localhost:5000
```

### 4. Open in Browser

Visit **http://localhost:5000** and follow the wizard:

1. Pick a **character** (Dragon, Bunny, Robot, Princess, Dinosaur, or Owl)
2. Pick a **place** (Forest, Castle, Space, Ocean, etc.)
3. Pick a **favourite colour**
4. Watch your personalised story appear with an AI illustration!

---

## 🔒 Password Protection

By default the app is open access. To require a password:

1. Click the **⚙️ Settings** icon in the top-right
2. Scroll to **🔒 Password Protection**
3. Enter and confirm a password, then click **🔒 Save Password**

To remove the password, leave both fields blank and click Save. While authenticated, your session is stored in a long-lived browser cookie so you won't be logged out on restart.

---

## 🔧 Configuring Ollama

### Option 1: Settings UI (Easiest)

1. Click **⚙️ Settings** in the top-right
2. Under **🤖 Ollama Configuration**, update the server URL and/or model name
3. Click **🔍 Test Connection** to verify, then **💾 Save Settings**

### Option 2: `.env` File (Recommended for servers)

Create a `.env` file next to `app.py`:

```env
OLLAMA_HOST=http://192.168.1.100:11434
OLLAMA_MODEL=gemma2:2b
```

Then run `python app.py` as normal.

### Option 3: Inline Environment Variable

```bash
OLLAMA_HOST=http://192.168.1.100:11434 python app.py
```

---

## 📖 Customising the Story Prompt

The prompt template can be edited live in **⚙️ Settings → 📖 Story Generation Prompt**. Use these placeholders:

| Placeholder | Replaced with |
|-------------|--------------|
| `{character}` | The chosen character (e.g. `brave dragon`) |
| `{setting}` | The chosen place (e.g. `enchanted forest`) |
| `{colour}` | The chosen colour (e.g. `blue`) |

Click **🔄 Reset to Default** to restore the original prompt at any time.

---

## 📁 Project Structure

```
.
├── app.py                      # Flask backend (routes, DB, Ollama + Pollinations.ai integration)
├── requirements.txt            # Python dependencies
├── deploy/
│   └── storytime.service       # systemd unit file for production deployment
├── instance/                   # Created at runtime (git-ignored)
│   ├── storytime.db            # SQLite database (settings + stories)
│   ├── images/                 # Downloaded AI illustrations
│   └── secret_key              # Persisted Flask secret key
├── templates/
│   ├── index.html              # Step 1 — character picker
│   ├── places.html             # Step 2 — place picker
│   ├── colors.html             # Step 3 — colour picker
│   ├── story.html              # Story display & read-aloud
│   ├── previous_stories.html   # Story history browser
│   ├── settings.html           # Settings UI
│   └── login.html              # Password login page
└── static/
    ├── style.css               # Child-friendly styling
    └── script.js               # Picker & story interaction logic
```

---

## 🚢 Production Deployment (Linux / systemd)

A ready-to-use Gunicorn + systemd service file is included.

### 1. Copy Files to the Server

```bash
sudo mkdir -p /srv/storytime
sudo cp -r . /srv/storytime/
cd /srv/storytime
python -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Create the Environment File

```bash
sudo tee /srv/storytime/.env <<'EOF'
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=gemma2:2b
EOF
```

### 3. Install the systemd Service

```bash
sudo cp deploy/storytime.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now storytime
```

The service runs as `nobody`, writes logs to `/var/log/storytime/`, and exposes a Unix socket at `/run/storytime/storytime.sock` — suitable for proxying via nginx or Caddy.

### 4. (Optional) nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name storytime.example.com;

    location / {
        proxy_pass http://unix:/run/storytime/storytime.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 🔧 Troubleshooting

### "Cannot connect to Ollama"
- Verify Ollama is running: `ollama serve`
- Check the host/port in **⚙️ Settings** or your `.env` file
- Use **🔍 Test Connection** to get an immediate diagnosis

### Story generation is slow
- The first request loads the model into memory — subsequent ones are faster
- Smaller models (`gemma2:2b`) are significantly faster than larger ones
- Try `ollama pull gemma2:2b` for the best speed/quality balance

### Image not appearing
- Pollinations.ai generation can take up to 60 seconds — the page shows a spinner while waiting
- If it times out, the story is still saved; re-visiting it from **📚 Previous Stories** will show the text without an image

### Text-to-speech not working
- Supported in Chrome, Edge, and Safari; inconsistent in Firefox
- Requires HTTPS or `localhost` (browser security restriction)

### "Instance" folder / database location
- All runtime data (`storytime.db`, images, secret key) lives in `instance/` which is git-ignored
- Do **not** delete `instance/` on a running server — it contains all your saved stories and settings

---

## 📜 License

Free to use and modify! Enjoy creating magical bedtime stories. ✨

---

## 🙏 Credits

- **[Ollama](https://ollama.ai)** — Local LLM inference
- **[Pollinations.ai](https://pollinations.ai)** — Free AI image generation
- **[Flask](https://flask.palletsprojects.com)** — Web framework
- **[Gunicorn](https://gunicorn.org)** — WSGI server for production
- **Web Speech API** — Browser read-aloud functionality

---

**Happy storytelling!** 📖✨🌙
