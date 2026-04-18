# 🌟 Magical Storybook Generator 🌟

A delightful Flask app that generates custom illustrated bedtime stories for kids aged 3+. Pick a character, a setting, and a color — get a unique story with AI-generated images!

## ✨ Features

- **Simple 3-year-old-friendly UI** — Big buttons, bright colors, emoji
- **AI Story Generation** — Uses Ollama (local LLM) for text
- **Auto-illustrated** — Unsplash provides curated, reliable images (no API key needed!)
- **Read-Aloud** — Browser text-to-speech reads the story to kids
- **Printable** — Save stories as keepsakes
- **Unique Every Time** — Fresh story each session

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Ollama installed and running locally ([download here](https://ollama.ai))

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Pull an Ollama Model

Make sure Ollama is running, then pull a model:

```bash
# Recommended (faster, good for kids)
ollama pull llama2

# Or try these alternatives:
ollama pull mistral
ollama pull neural-chat
```

Start Ollama server (if not already running):
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
🤖 Ollama Model: llama2
Visit http://localhost:5000
⚙️  Click the settings icon to change Ollama address if needed
```

### 4. Open in Browser

Visit **http://localhost:5000** and pick a character, setting, and color to generate your story!

---

## 🔧 Configuring Ollama Address

You have three ways to set your Ollama server address:

### Option 1: Environment Variables (Recommended)

Create a `.env` file in the same directory as `app.py`:

```env
OLLAMA_HOST=http://192.168.1.100:11434
OLLAMA_MODEL=llama2
```

Then run:
```bash
python app.py
```

### Option 2: Settings UI (Easiest)

1. Click the **⚙️ Settings** button in the top-right of the app
2. Enter your Ollama address (e.g., `http://192.168.1.100:11434`)
3. Click **🔍 Test Connection** to verify
4. Click **💾 Save**

### Option 3: Command Line

```bash
OLLAMA_HOST=http://192.168.1.100:11434 python app.py
```

---

## 📁 Project Structure

```
.
├── app.py                 # Flask backend
├── requirements.txt       # Python dependencies
├── templates/
│   ├── index.html        # Character/setting/color picker
│   └── story.html        # Story display & read-aloud
└── static/
    ├── style.css         # Child-friendly styling
    └── script.js         # Interactive picker logic
```

---

## 🎨 Customization

### Change the Ollama Model
Edit `app.py`, line 10:
```python
OLLAMA_MODEL = "llama2"  # Change to "mistral", "neural-chat", etc.
```

### Add More Characters/Settings
Edit `templates/index.html` — add more `<button>` elements in the button grids:
```html
<button class="choice-btn" data-type="character" data-value="friendly turtle">🐢 Turtle</button>
```

### Adjust Story Length
In `app.py`, edit the prompt (line 27):
```python
prompt = f"""Write a short, gentle bedtime story for a 3-year-old (about 200 words)...
```

### Use a Different Image API

The app uses **Unsplash** (reliable, curated images). If you want alternatives:

**Pexels** (similar quality):
```python
img_url = f"https://images.pexels.com/search/{encoded_query}?auto=compress&cs=tinysrgb&fit=max&w=600&h=400"
```

**Picsum.photos** (simple placeholder service):
```python
img_url = f"https://picsum.photos/600/400?random={index}"
```

**Local Images** — Download some images and serve them instead:
```python
img_url = f"/static/images/story_{index}.jpg"
```

---

## 🔧 Troubleshooting

### "Cannot connect to Ollama"
- Make sure Ollama is running: `ollama serve`
- Check it's on `localhost:11434`

### Images not loading
- Unsplash may be rate-limited. Try refreshing after a few seconds.
- Or switch to a different image API (see Customization section above).

### Story generation is slow
- First run takes longer as Ollama loads the model.
- Smaller models like `llama2` are faster than `mistral`.
- Use `ollama pull neural-chat` for a lightweight option.

### Text-to-speech not working
- Only works in Chrome, Edge, Safari (not Firefox consistently).
- Requires HTTPS or localhost (security restriction).

---

## 🎯 Ideas for Extensions

- **Save & Share** — Store stories as JSON/PDF
- **Themes** — Different UI themes (space, underwater, etc.)
- **Multi-language** — Prompt Ollama to generate in other languages
- **Drawing Canvas** — Let kids draw on story images
- **Sound Effects** — Add ambient sounds while reading
- **Story History** — Let parents review past stories
- **Difficulty Levels** — Adjust story complexity by age

---

## 📜 License

Free to use and modify! Enjoy creating magical bedtime stories. ✨

---

## 🙏 Credits

- **Ollama** — Local LLM inference
- **Pollinations.ai** — Free AI image generation
- **Flask** — Web framework
- **Web Speech API** — Read-aloud functionality

---

**Happy storytelling!** 📖✨🌙
