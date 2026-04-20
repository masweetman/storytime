from flask import Flask, render_template, request, jsonify, send_from_directory, abort, session, redirect, url_for, make_response, send_file
import json
import requests
import re
import os
import uuid
import secrets
import functools
from io import BytesIO
from urllib.parse import quote as url_quote
from dotenv import load_dotenv
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from gtts import gTTS
from flask_gtts import gtts as FlaskGTTS
import threading

load_dotenv()

app = Flask(__name__, instance_path=str(Path(__file__).parent / 'instance'))
FlaskGTTS(app)

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

# Audio configuration — stored inside instance/ so they're excluded from git
AUDIO_DIR = Path(app.instance_path) / 'audio'
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Default settings
DEFAULT_SETTINGS = {
    'ollama_host': 'http://localhost:11434',
    'ollama_model': 'gemma2:2b',
    'llm_provider': 'ollama',
    'openrouter_api_key': '',
    'openrouter_model': 'openrouter/free',
    'tts_locale': 'en-uk',
    'tts_slow': 'true',
    'password': '',
    'story_prompt': '''You are an engaging storyteller. Write a short, exciting adventure story for a 3-year-old child (about 150 words).

Main character: A {character}
Setting: {setting}
Favorite color: {colour}

The story should:
- Use natural language
- Involve the character and a friend going on an adventure
- Minimize alliteration, rhyme, and rhythm, but do not eliminate them completely.

Story:'''
}

TTS_LOCALE_CONFIG = {
    'en-us': {'lang': 'en', 'tld': 'com'},
    'en-uk': {'lang': 'en', 'tld': 'co.uk'},
    'en-au': {'lang': 'en', 'tld': 'com.au'},
}

TTS_SLOW_CONFIG = {
    'true': True,
    'false': False,
}

STARTUP_MIGRATIONS = [
    ('001_add_audio_path_to_stories', 'Add audio_path column to stories table', 'stories', 'audio_path', 'TEXT'),
]

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
                audio_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Insert defaults if they don't exist
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                (key, value)
            )

def column_exists(conn, table_name, column_name):
    """Return True if the given SQLite table has the requested column."""
    rows = conn.execute(f'PRAGMA table_info({table_name})').fetchall()
    return any(row['name'] == column_name for row in rows)

def apply_migrations():
    """Apply pending SQLite schema migrations during application startup."""
    with get_db() as conn:
        applied = {
            row['version']
            for row in conn.execute('SELECT version FROM schema_migrations').fetchall()
        }

        for version, description, table_name, column_name, column_type in STARTUP_MIGRATIONS:
            if version in applied:
                continue

            if column_exists(conn, table_name, column_name):
                print(f"ℹ️  Migration already satisfied: {version} ({column_name} exists)")
            else:
                print(f"🔄 Running migration: {version} - {description}")
                conn.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')
                print(f"✅ Migration {version} completed")

            conn.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, description) VALUES (?, ?)',
                (version, description)
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

def get_tts_locale(locale=None):
    """Return a valid stored TTS locale value."""
    locale_value = (locale or DEFAULT_SETTINGS['tts_locale']).lower()
    return locale_value if locale_value in TTS_LOCALE_CONFIG else DEFAULT_SETTINGS['tts_locale']

def get_tts_slow_value(slow_value=None):
    """Return the configured gTTS slow boolean."""
    normalized_value = str(slow_value or DEFAULT_SETTINGS['tts_slow']).lower()
    return TTS_SLOW_CONFIG.get(normalized_value, False)

def save_story(character, setting, colour, story_text, image_path, audio_path=None):
    """Persist a generated story to the database"""
    with get_db() as conn:
        cursor = conn.execute(
            '''INSERT INTO stories (character, setting, colour, story_text, image_path, audio_path)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (character, setting, colour, story_text, image_path, audio_path)
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

# Apply pending migrations on startup
apply_migrations()

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

# ─── Main pages (NO authentication required) ────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/places')
def places():
    return render_template('places.html')

@app.route('/colors')
def colors():
    return render_template('colors.html')

@app.route('/story')
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

@app.route('/previous-stories')
def previous_stories():
    stories = get_all_stories()
    return render_template(
        'previous_stories.html',
        stories=stories,
        stories_json=json.dumps(stories),
        colour_map=COLOUR_MAP,
    )

# ─── Settings page (REQUIRES authentication) ──────────────────────────────────

@app.route('/settings', methods=['GET', 'POST'])
@require_auth
def settings():
    """Settings page — requires authentication"""
    if request.method == 'POST':
        # Handle form submission
        password = request.form.get('password', '')
        ollama_host = request.form.get('ollama_host', '')
        ollama_model = request.form.get('ollama_model', '')
        openrouter_api_key = request.form.get('openrouter_api_key', '')
        openrouter_model = request.form.get('openrouter_model', '')
        llm_provider = request.form.get('llm_provider', 'ollama')
        tts_locale = request.form.get('tts_locale', DEFAULT_SETTINGS['tts_locale'])
        tts_slow = request.form.get('tts_slow', DEFAULT_SETTINGS['tts_slow'])
        story_prompt = request.form.get('story_prompt', '')

        if password:
            set_setting('password', password)
        if ollama_host:
            set_setting('ollama_host', ollama_host)
        if ollama_model:
            set_setting('ollama_model', ollama_model)
        if openrouter_api_key:
            set_setting('openrouter_api_key', openrouter_api_key)
        if openrouter_model:
            set_setting('openrouter_model', openrouter_model)
        if llm_provider:
            set_setting('llm_provider', llm_provider)
        set_setting('tts_locale', get_tts_locale(tts_locale))
        set_setting('tts_slow', 'true' if get_tts_slow_value(tts_slow) else 'false')
        if story_prompt:
            set_setting('story_prompt', story_prompt)

        return redirect(url_for('settings'))

    settings_dict = get_all_settings()
    return render_template('settings.html', settings=settings_dict)

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve story images stored in instance/images/ (outside the static folder)."""
    return send_from_directory(IMAGES_DIR, filename)

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """Serve story audio files stored in instance/audio/ (outside the static folder)."""
    return send_from_directory(AUDIO_DIR, filename)

@app.route('/api/config', methods=['POST'])
@require_auth_api
def api_config():
    """Test and save Ollama configuration"""
    if not request.json:
        return jsonify({'success': False, 'error': 'Invalid JSON'}), 400
    
    ollama_host = request.json.get('ollama_host', '')
    if not ollama_host:
        return jsonify({'success': False, 'error': 'Ollama host not provided'}), 400
    
    # Test the connection
    try:
        test_url = f"{ollama_host}/api/tags"
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            # Connection successful, save the host
            set_setting('ollama_host', ollama_host)
            return jsonify({'success': True, 'message': 'Connection successful'})
        else:
            return jsonify({'success': False, 'error': f'Ollama returned status {response.status_code}'}), 400
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Connection timeout'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'error': 'Cannot connect to Ollama server'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': f'Connection error: {str(e)}'}), 500

# OpenRouter model list proxy
# Update the existing models endpoint to accept both GET and POST
@app.route('/api/openrouter/models', methods=['GET', 'POST'])
@require_auth_api
def get_openrouter_models():
    """Fetch available OpenRouter models using provided or stored API key"""
    provided_api_key = ''
    api_key = ''
    if request.method == 'POST' and request.json:
        provided_api_key = (request.json.get('api_key', '') or '').strip()
        api_key = provided_api_key

    if not api_key:
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
        # Sort models by name
        models.sort()

        if provided_api_key:
            # Persist only after successful validation against OpenRouter.
            set_setting('openrouter_api_key', provided_api_key)

        return jsonify({'success': True, 'models': models})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error fetching models: {str(e)}'}), 500

# Add this new endpoint after the get_openrouter_models function
@app.route('/api/openrouter/test-connection', methods=['POST'])
@require_auth_api
def test_openrouter_connection():
    """Test OpenRouter connection with provided or stored API key"""
    provided_api_key = (request.json.get('api_key', '') if request.json else '') or ''
    provided_api_key = provided_api_key.strip()
    api_key = provided_api_key

    if not api_key:
        api_key = get_setting('openrouter_api_key', '')
    
    if not api_key:
        return jsonify({'success': False, 'error': 'OpenRouter API key not provided'}), 400
    
    try:
        resp = requests.get('https://openrouter.ai/api/v1/models', headers={
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': 'http://127.0.0.1:5000',
            'X-Title': 'Storybook Generator'
        }, timeout=10)
        
        if resp.status_code == 200:
            if provided_api_key:
                # Persist only after successful validation.
                set_setting('openrouter_api_key', provided_api_key)
            return jsonify({'success': True, 'message': 'Connection successful'})
        else:
            return jsonify({'success': False, 'error': f'OpenRouter returned {resp.status_code}: {resp.text[:100]}'}), resp.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': f'Connection failed: {str(e)}'}), 500

@app.route('/api/tts', methods=['POST'])
def api_tts():
    """Generate TTS audio for story text using gTTS. If story_id provided, try to serve pre-generated audio."""
    if not request.json:
        return jsonify({'success': False, 'error': 'Invalid JSON'}), 400

    text = (request.json.get('text', '') or '').strip()
    story_id = request.json.get('story_id')

    if not text and not story_id:
        return jsonify({'success': False, 'error': 'No text provided'}), 400

    # If story_id provided, reuse existing audio or persist a new file for this story.
    if story_id:
        story = get_story_by_id(story_id)
        if story:
            story_text = (story.get('story_text') or '').strip()
            text = text or story_text

            if story.get('audio_path'):
                audio_filename = story['audio_path'].split('/')[-1]
                audio_file = AUDIO_DIR / audio_filename
                if audio_file.exists():
                    return send_from_directory(AUDIO_DIR, audio_filename)
                print(f"⚠️  Audio path exists for story {story_id} but file is missing; regenerating.")

            if text:
                audio_path = save_audio_file(text, story_id)
                if audio_path:
                    audio_filename = audio_path.split('/')[-1]
                    return send_from_directory(AUDIO_DIR, audio_filename)

        elif not text:
            return jsonify({'success': False, 'error': 'Story not found'}), 404

    # Generate audio on-demand
    locale = get_tts_locale(get_setting('tts_locale', DEFAULT_SETTINGS['tts_locale']))
    locale_config = TTS_LOCALE_CONFIG[locale]
    slow_value = get_tts_slow_value(get_setting('tts_slow', DEFAULT_SETTINGS['tts_slow']))
    audio_buffer = BytesIO()

    try:
        tts_audio = gTTS(
            text=text,
            lang=locale_config['lang'],
            tld=locale_config['tld'],
            slow=slow_value,
        )
        tts_audio.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        return send_file(
            audio_buffer,
            mimetype='audio/mpeg',
            as_attachment=False,
            download_name='story.mp3',
            max_age=0,
        )
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to generate audio: {str(e)}'}), 500

@app.route('/api/settings', methods=['GET', 'POST'])
@require_auth_api
def api_settings():
    """Get or save settings as JSON"""
    if request.method == 'GET':
        # Return all settings
        settings = get_all_settings()
        settings['openrouter_api_key_set'] = bool(settings.get('openrouter_api_key'))
        return jsonify(settings)
    
    # POST — save settings
    if not request.json:
        return jsonify({'success': False, 'error': 'Invalid JSON'}), 400
    
    data = request.json
    
    # Save each setting that was provided
    if 'password' in data and data['password']:
        set_setting('password', data['password'])
    if 'ollama_host' in data and data['ollama_host']:
        set_setting('ollama_host', data['ollama_host'])
    if 'ollama_model' in data and data['ollama_model']:
        set_setting('ollama_model', data['ollama_model'])
    if 'openrouter_api_key' in data and data['openrouter_api_key']:
        set_setting('openrouter_api_key', data['openrouter_api_key'])
    if 'openrouter_model' in data and data['openrouter_model']:
        set_setting('openrouter_model', data['openrouter_model'])
    if 'llm_provider' in data and data['llm_provider']:
        set_setting('llm_provider', data['llm_provider'])
    if 'tts_locale' in data:
        set_setting('tts_locale', get_tts_locale(data['tts_locale']))
    if 'tts_slow' in data:
        set_setting('tts_slow', 'true' if get_tts_slow_value(data['tts_slow']) else 'false')
    if 'story_prompt' in data and data['story_prompt']:
        set_setting('story_prompt', data['story_prompt'])
    
    return jsonify({'success': True, 'message': 'Settings saved'})

@app.route('/api/stories')
def api_stories():
    """Return all saved stories as JSON (public)"""
    return jsonify(get_all_stories())

@app.route('/api/stories/<int:story_id>')
def api_story(story_id):
    """Return a single saved story as JSON (public)"""
    story = get_story_by_id(story_id)
    if story:
        return jsonify(story)
    return jsonify({'error': 'Story not found'}), 404

@app.route('/api/delete-story/<int:story_id>', methods=['DELETE'])
def delete_story(story_id):
    """Delete a story and its associated files (image, audio) from disk."""
    @require_auth_api
    def _delete():
        story = get_story_by_id(story_id)
        if not story:
            return jsonify({'success': False, 'error': 'Story not found'}), 404
        
        try:
            # Delete image file if it exists
            if story.get('image_path'):
                image_filename = story['image_path'].split('/')[-1]
                image_file = IMAGES_DIR / image_filename
                if image_file.exists():
                    image_file.unlink()
                    print(f"🗑️  Deleted image file: {image_file}")
            
            # Delete audio file if it exists
            if story.get('audio_path'):
                audio_filename = story['audio_path'].split('/')[-1]
                audio_file = AUDIO_DIR / audio_filename
                if audio_file.exists():
                    audio_file.unlink()
                    print(f"🗑️  Deleted audio file: {audio_file}")
            
            # Delete story from database
            with get_db() as conn:
                conn.execute('DELETE FROM stories WHERE id = ?', (story_id,))
            print(f"🗑️  Deleted story {story_id} from database")
            
            return jsonify({'success': True, 'message': 'Story deleted'})
        
        except Exception as e:
            print(f"❌ Error deleting story {story_id}: {e}")
            return jsonify({'success': False, 'error': f'Error deleting story: {str(e)}'}), 500
    
    return _delete()

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

def save_audio_file(text, story_id):
    """Generate and save audio MP3 file for story text using user's TTS settings."""
    try:
        filename = f"{uuid.uuid4().hex}.mp3"
        print(f"🎵 Generating audio for story {story_id} (filename: {filename})...")
        
        # Get user's TTS settings
        locale = get_tts_locale(get_setting('tts_locale', DEFAULT_SETTINGS['tts_locale']))
        locale_config = TTS_LOCALE_CONFIG[locale]
        slow_value = get_tts_slow_value(get_setting('tts_slow', DEFAULT_SETTINGS['tts_slow']))
        
        # Generate audio
        tts_audio = gTTS(
            text=text,
            lang=locale_config['lang'],
            tld=locale_config['tld'],
            slow=slow_value,
        )
        
        # Save to disk
        audio_path = AUDIO_DIR / filename
        tts_audio.save(str(audio_path))
        print(f"✅ Saved audio for story {story_id} → {audio_path}")
        
        # Update database with audio_path
        with get_db() as conn:
            conn.execute(
                'UPDATE stories SET audio_path = ? WHERE id = ?',
                (f"/audio/{filename}", story_id)
            )
        print(f"💾 Updated story {story_id} with audio_path")
        
        return f"/audio/{filename}"
        
    except Exception as e:
        print(f"⚠️  Error generating audio for story {story_id}: {type(e).__name__}: {e}")
        # Don't raise—let story exist without audio
        return None

def generate_audio_background(text, story_id):
    """Background task to generate audio asynchronously."""
    try:
        save_audio_file(text, story_id)
    except Exception as e:
        print(f"⚠️  Background audio generation failed for story {story_id}: {e}")

@app.route('/api/generate-story', methods=['POST'])
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
        
        # Spawn background task to generate audio (non-blocking)
        audio_thread = threading.Thread(
            target=generate_audio_background,
            args=(story_text, story_id),
            daemon=True
        )
        audio_thread.start()
        print(f"🎵 Started background audio generation for story {story_id}")

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
