from flask import Flask, render_template, request, jsonify, send_from_directory, abort, session, redirect, url_for, make_response
import json
import requests
import re
import os
import uuid
import secrets
import functools
from urllib.parse import quote as url_quote
from dotenv import load_dotenv
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from datetime import timedelta

load_dotenv()

app = Flask(__name__, instance_path=str(Path(__file__).parent / 'instance'))

# ─── Secret key (persisted so sessions survive restarts) ──────────────────────
_secret_key_file = Path(app.instance_path) / 'secret_key'
_secret_key_file.parent.mkdir(parents=True, exist_ok=True)
if _secret_key_file.exists():
    app.secret_key = _secret_key_file.read_bytes()
else:
    app.secret_key = secrets.token_bytes(32)
    _secret_key_file.write_bytes(app.secret_key)

# Sessions last 10 years — effectively a non-expiring cookie
app.permanent_session_lifetime = timedelta(days=3650)

# Database configuration — stored in the instance folder
DB_PATH = Path(app.instance_path) / 'storytime.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Image configuration — stored inside instance/ so they're excluded from git
IMAGES_DIR = Path(app.instance_path) / 'images'
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Default settings
DEFAULT_SETTINGS = {
    'ollama_host': 'http://localhost:11434',
    'ollama_model': 'gemma2:2b',
    'llm_provider': 'ollama',
    'openrouter_api_key': '',
    'openrouter_model': 'openai/gpt-4o-mini',
    'password': '',
    'story_prompt': '''Write a short, gentle bedtime story for a 3-year-old child (about 150 words).

Main character: A {character}
Setting: {setting}
Favorite color: {colour}

The story should:
- Be simple and calming
- Have a happy ending
- End with the character falling asleep or getting ready for bed
- Use rhyming or rhythmic language where possible

Story:'''
}

@contextmanager
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    """Initialize database with settings and stories tables"""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                setting TEXT NOT NULL,
                colour TEXT NOT NULL,
                story_text TEXT NOT NULL,
                image_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Insert defaults if they don't exist
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                (key, value)
            )

def get_setting(key, default=None):
    """Get a setting from database"""
    with get_db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default

def set_setting(key, value):
    """Set a setting in database"""
    with get_db() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
            (key, value)
        )

def get_all_settings():
    """Get all settings"""
    with get_db() as conn:
        rows = conn.execute('SELECT key, value FROM settings').fetchall()
        return {row['key']: row['value'] for row in rows}

def save_story(character, setting, colour, story_text, image_path):
    """Persist a generated story to the database"""
    with get_db() as conn:
        cursor = conn.execute(
            '''INSERT INTO stories (character, setting, colour, story_text, image_path)
               VALUES (?, ?, ?, ?, ?)''',
            (character, setting, colour, story_text, image_path)
        )
        return cursor.lastrowid

def get_all_stories():
    """Return all saved stories, newest first"""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM stories ORDER BY created_at DESC'
        ).fetchall()
        return [dict(row) for row in rows]

def get_story_by_id(story_id):
    """Return a single story by its primary key"""
    with get_db() as conn:
        row = conn.execute(
            'SELECT * FROM stories WHERE id = ?', (story_id,)
        ).fetchone()
        return dict(row) if row else None

# Initialize database on startup
init_db()

# ─── Auth helpers ──────────────────────────────────────────────────────────────

def is_authenticated():
    """Return True if no password is set, or if the session is authenticated."""
    password = get_setting('password', '')
    if not password:
        return True
    return session.get('authenticated') is True

def require_auth(f):
    """Decorator: redirect to /login for page routes if not authenticated."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def require_auth_api(f):
    """Decorator: return 401 JSON for API routes if not authenticated."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not is_authenticated():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# Ollama configuration - read from database
OLLAMA_HOST = get_setting('ollama_host', 'http://localhost:11434')
OLLAMA_MODEL = get_setting('ollama_model', 'gemma2:2b')
OLLAMA_API = f"{OLLAMA_HOST}/api/generate"

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        entered = request.form.get('password', '')
        stored  = get_setting('password', '')
        if not stored or entered == stored:
            session.permanent = True
            session['authenticated'] = True
            next_url = request.form.get('next') or url_for('index')
            return redirect(next_url)
        return render_template('login.html', error='Incorrect password', next=request.form.get('next', ''))
    # GET — if no password set or already authenticated, skip login
    if is_authenticated():
        return redirect(url_for('index'))
    return render_template('login.html', next=request.args.get('next', ''))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@require_auth
def index():
    return render_template('index.html')

@app.route('/places')
@require_auth
def places():
    return render_template('places.html')

@app.route('/colors')
@require_auth
def colors():
    return render_template('colors.html')

@app.route('/story')
@require_auth
def story():
    return render_template('story.html')

# Rough colour → CSS background mapping for the card tags
COLOUR_MAP = {
    'red':    '#e74c3c',
    'orange': '#e67e22',
    'yellow': '#f1c40f',
    'green':  '#27ae60',
    'blue':   '#2980b9',
    'purple': '#8e44ad',
    'pink':   '#e91e8c',
    'white':  '#aaa',
    'black':  '#333',
    'brown':  '#795548',
    'grey':   '#607d8b',
    'gray':   '#607d8b',
}

@app.route('/images/<path:filename>')
@require_auth
def serve_image(filename):
    """Serve story images stored in instance/images/ (outside the static folder)."""
    return send_from_directory(IMAGES_DIR, filename)

@app.route('/previous-stories')
@require_auth
def previous_stories():
    stories = get_all_stories()
    return render_template(
        'previous_stories.html',
        stories=stories,
        stories_json=json.dumps(stories),
        colour_map=COLOUR_MAP,
    )

@app.route('/settings')
@require_auth
def settings_page():
    return render_template('settings.html')

# ─── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
@require_auth_api
def get_settings():
    """Get all settings (password is never returned to the client)"""
    s = get_all_settings()
    s.pop('password', None)          # never expose the stored password
    s['password_set'] = bool(get_setting('password', ''))
    # Add provider and OpenRouter info (mask API key)
    s['llm_provider'] = get_setting('llm_provider', 'ollama')
    s['openrouter_model'] = get_setting('openrouter_model', '')
    s['openrouter_api_key_set'] = bool(get_setting('openrouter_api_key', ''))
    return jsonify(s)

@app.route('/api/settings', methods=['POST'])
@require_auth_api
def update_settings():
    """Update settings"""
    data = request.json

    for key, value in data.items():
        if key in DEFAULT_SETTINGS:
            set_setting(key, value)
            print(f"✅ Updated setting: {key}")
        else:
            return jsonify({
                'success': False,
                'error': f'Unknown setting: {key}'
            }), 400

    # Update global variables
    global OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_API
    OLLAMA_HOST = get_setting('ollama_host', 'http://localhost:11434')
    OLLAMA_MODEL = get_setting('ollama_model', 'gemma2:2b')
    OLLAMA_API = f"{OLLAMA_HOST}/api/generate"

    return jsonify({'success': True, 'message': 'Settings updated successfully'})

@app.route('/api/config', methods=['GET'])
@require_auth_api
def get_config():
    """Get current Ollama configuration"""
    return jsonify({'ollama_host': OLLAMA_HOST, 'ollama_model': OLLAMA_MODEL})

@app.route('/api/config', methods=['POST'])
@require_auth_api
def set_config():
    """Update Ollama configuration"""
    global OLLAMA_HOST, OLLAMA_API
    data = request.json
    new_host = data.get('ollama_host', OLLAMA_HOST).rstrip('/')

    try:
        test_response = requests.get(f"{new_host}/api/tags", timeout=5)
        if test_response.status_code == 200:
            OLLAMA_HOST = new_host
            OLLAMA_API = f"{OLLAMA_HOST}/api/generate"
            return jsonify({
                'success': True,
                'message': 'Ollama connection updated successfully',
                'ollama_host': OLLAMA_HOST
            })
        else:
            return jsonify({'success': False, 'error': 'Ollama server returned an error'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Cannot connect to Ollama at that address'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500

# OpenRouter model list proxy
# Update the existing models endpoint to accept both GET and POST
@app.route('/api/openrouter/models', methods=['GET', 'POST'])
@require_auth_api
def get_openrouter_models():
    """Fetch available OpenRouter models using stored API key"""
    api_key = get_setting('openrouter_api_key', '')
    if not api_key:
        return jsonify({'success': False, 'error': 'OpenRouter API key not set'}), 400
    try:
        resp = requests.get('https://openrouter.ai/api/v1/models', headers={
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': 'http://127.0.0.1:5000',
            'X-Title': 'Storybook Generator'
        }, timeout=10)
        if resp.status_code != 200:
            return jsonify({'success': False, 'error': f'OpenRouter returned {resp.status_code}'}), resp.status_code
        data = resp.json()
        # Extract model IDs (assuming OpenRouter returns a list under 'data')
        models = []
        if isinstance(data, dict) and 'data' in data:
            for m in data['data']:
                if isinstance(m, dict) and 'id' in m:
                    models.append(m['id'])
        else:
            # Fallback: if response is a list
            if isinstance(data, list):
                for m in data:
                    if isinstance(m, dict) and 'id' in m:
                        models.append(m['id'])
        return jsonify({'success': True, 'models': models})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error fetching models: {str(e)}'}), 500

# Add this new endpoint after the get_openrouter_models function
@app.route('/api/openrouter/test-connection', methods=['POST'])
@require_auth_api
def test_openrouter_connection():
    """Test OpenRouter connection with the provided API key"""
    api_key = request.json.get('api_key', '') if request.json else ''
    
    if not api_key:
        return jsonify({'success': False, 'error': 'OpenRouter API key not provided'}), 400
    
    try:
        resp = requests.get('https://openrouter.ai/api/v1/models', headers={
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': 'http://127.0.0.1:5000',
            'X-Title': 'Storybook Generator'
        }, timeout=10)
        
        if resp.status_code == 200:
            return jsonify({'success': True, 'message': 'Connection successful'})
        else:
            return jsonify({'success': False, 'error': f'OpenRouter returned {resp.status_code}: {resp.text[:100]}'}), resp.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': f'Connection failed: {str(e)}'}), 500

@app.route('/api/stories')
@require_auth_api
def api_stories():
    """Return all saved stories as JSON"""
    return jsonify(get_all_stories())

@app.route('/api/stories/<int:story_id>')
@require_auth_api
def api_story(story_id):
    """Return a single saved story as JSON"""
    story = get_story_by_id(story_id)
    if story:
        return jsonify(story)
    return jsonify({'error': 'Story not found'}), 404

def download_and_save_image(prompt):
    """Download image from Pollinations.ai, save to instance/images/, return URL path."""
    try:
        filename = f"{uuid.uuid4().hex}.png"
        print(f"📥 Downloading image from Pollinations.ai (filename: {filename})...")
        print(f"   Prompt: {prompt[:60]}...")

        encoded_prompt = url_quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"

        print(f"   Waiting for Pollinations.ai to generate image...")
        response = requests.get(image_url, timeout=120)

        print(f"   Response status: {response.status_code}, size: {len(response.content)} bytes")

        if response.status_code == 200:
            image_path = IMAGES_DIR / filename
            with open(image_path, 'wb') as f:
                f.write(response.content)
            print(f"✅ Saved image ({len(response.content)} bytes) → {image_path}")
            # Return the URL that our /images/<filename> route will serve
            return f"/images/{filename}"
        else:
            print(f"⚠️  Failed to download image: HTTP {response.status_code}")
            return None

    except requests.exceptions.Timeout:
        print(f"⚠️  Timeout downloading image")
        return None
    except Exception as e:
        print(f"⚠️  Error downloading image: {type(e).__name__}: {e}")
        return None

@app.route('/api/generate-story', methods=['POST'])
@require_auth_api
def generate_story():
    """Generate a story using the selected LLM provider (Ollama or OpenRouter)"""
    data = request.json
    character = data.get('character', 'dragon')
    setting = data.get('setting', 'forest')
    colour = data.get('colour', 'blue')

    prompt_template = get_setting('story_prompt', DEFAULT_SETTINGS['story_prompt'])
    prompt = prompt_template.format(character=character, setting=setting, colour=colour)

    # Determine provider
    provider = get_setting('llm_provider', 'ollama')
    try:
        if provider == 'ollama':
            print(f"📝 Generating story with Ollama model: {OLLAMA_MODEL}")
            print(f"📡 Using Ollama at: {OLLAMA_HOST}")
            response = requests.post(
                OLLAMA_API,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.7,
                },
                timeout=120
            )
            if response.status_code != 200:
                raise Exception(f"Ollama error: {response.text[:100]}")
            response_data = response.json()
            story_text = response_data.get('response', '').strip()
        else:  # OpenRouter
            api_key = get_setting('openrouter_api_key', '')
            model = get_setting('openrouter_model', '')
            if not api_key or not model:
                return jsonify({'success': False, 'error': 'OpenRouter API key or model not configured'}), 400
            print(f"📝 Generating story with OpenRouter model: {model}")
            openrouter_url = 'https://openrouter.ai/api/v1/chat/completions'
            response = requests.post(
                openrouter_url,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                    'HTTP-Referer': 'http://127.0.0.1:5000',  # 👈 ADD THIS
                    'X-Title': 'Storybook Generator'  # Optional
                },
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': 'You are a helpful assistant that writes short bedtime stories.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.7,
                },
                timeout=120
            )
            if response.status_code != 200:
                raise Exception(f"OpenRouter error: {response.text[:100]}")
            response_data = response.json()
            # OpenAI style response
            story_text = response_data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

        if not story_text:
            return jsonify({'success': False, 'error': 'Generated story is empty'}), 500

        # Generate illustration via Pollinations.ai (same for both providers)
        image_prompt = f"{character} in a {colour} {setting}, bedtime story illustration, cute cartoon style"
        img_url = download_and_save_image(image_prompt)
        image_urls = [img_url] if img_url else []

        # Persist story
        story_id = save_story(
            character=character,
            setting=setting,
            colour=colour,
            story_text=story_text,
            image_path=img_url
        )
        print(f"💾 Story saved to database with id={story_id}")

        return jsonify({
            'success': True,
            'story': story_text,
            'images': image_urls,
            'character': character,
            'setting': setting,
            'colour': colour,
            'story_id': story_id
        })
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
        return jsonify({'success': False, 'error': f'Connection error: {str(e)}'}), 500
    except requests.exceptions.Timeout:
        print(f"❌ Timeout waiting for LLM response")
        return jsonify({'success': False, 'error': 'LLM request timed out'}), 500
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 500

if __name__ == '__main__':
    print("🎉 Storybook Generator starting...")
    print(f"📡 Ollama Host: {OLLAMA_HOST}")
    print(f"🤖 Ollama Model: {OLLAMA_MODEL}")
    print(f"💾 Database: {DB_PATH}")
    print("Visit http://localhost:5000")
    app.run(debug=True, port=5000)
