from flask import Flask, render_template, request, jsonify, send_from_directory, abort
import json
import requests
import re
import os
import uuid
from urllib.parse import quote as url_quote
from dotenv import load_dotenv
from pathlib import Path
import sqlite3
from contextlib import contextmanager

load_dotenv()

app = Flask(__name__, instance_path=str(Path(__file__).parent / 'instance'))

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

# Ollama configuration - read from database
OLLAMA_HOST = get_setting('ollama_host', 'http://localhost:11434')
OLLAMA_MODEL = get_setting('ollama_model', 'gemma2:2b')
OLLAMA_API = f"{OLLAMA_HOST}/api/generate"

# ─── Routes ────────────────────────────────────────────────────────────────────

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

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve story images stored in instance/images/ (outside the static folder)."""
    return send_from_directory(IMAGES_DIR, filename)

@app.route('/previous-stories')
def previous_stories():
    stories = get_all_stories()
    return render_template(
        'previous_stories.html',
        stories=stories,
        stories_json=json.dumps(stories),
        colour_map=COLOUR_MAP,
    )

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

# ─── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings"""
    return jsonify(get_all_settings())

@app.route('/api/settings', methods=['POST'])
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
def get_config():
    """Get current Ollama configuration"""
    return jsonify({'ollama_host': OLLAMA_HOST, 'ollama_model': OLLAMA_MODEL})

@app.route('/api/config', methods=['POST'])
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

@app.route('/api/stories')
def api_stories():
    """Return all saved stories as JSON"""
    return jsonify(get_all_stories())

@app.route('/api/stories/<int:story_id>')
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
def generate_story():
    """Generate a story using Ollama based on user selections"""
    data = request.json
    character = data.get('character', 'dragon')
    setting = data.get('setting', 'forest')
    colour = data.get('colour', 'blue')

    prompt_template = get_setting('story_prompt', DEFAULT_SETTINGS['story_prompt'])
    prompt = prompt_template.format(character=character, setting=setting, colour=colour)

    try:
        print(f"📝 Generating story with model: {OLLAMA_MODEL}")
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

        print(f"Response status: {response.status_code}")

        if response.status_code == 200:
            response_data = response.json()
            story_text = response_data.get('response', '').strip()

            if not story_text:
                print(f"⚠️  Empty response from Ollama: {response_data}")
                return jsonify({
                    'success': False,
                    'error': 'Ollama returned an empty response. Check if the model is loaded.'
                }), 500

            # Generate a single illustration via Pollinations.ai
            image_prompt = f"{character} in a {colour} {setting}, bedtime story illustration, cute cartoon style"
            img_url = download_and_save_image(image_prompt)
            image_urls = [img_url] if img_url else []

            # ── Persist to database ──────────────────────────────────────────
            story_id = save_story(
                character=character,
                setting=setting,
                colour=colour,
                story_text=story_text,
                image_path=img_url  # may be None if generation failed
            )
            print(f"💾 Story saved to database with id={story_id}")

            print(f"✅ Story generated successfully ({len(story_text)} chars)")

            return jsonify({
                'success': True,
                'story': story_text,
                'images': image_urls,
                'character': character,
                'setting': setting,
                'colour': colour,
                'story_id': story_id
            })

        else:
            error_text = response.text
            print(f"❌ Ollama error (status {response.status_code}): {error_text}")
            return jsonify({
                'success': False,
                'error': f'Ollama error: {error_text[:100]}'
            }), 500

    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
        return jsonify({
            'success': False,
            'error': f'Cannot connect to Ollama at {OLLAMA_HOST}'
        }), 500
    except requests.exceptions.Timeout:
        print(f"❌ Timeout waiting for Ollama response")
        return jsonify({
            'success': False,
            'error': 'Ollama took too long to respond. Try a smaller model or check server.'
        }), 500
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)}'
        }), 500

if __name__ == '__main__':
    print("🎉 Storybook Generator starting...")
    print(f"📡 Ollama Host: {OLLAMA_HOST}")
    print(f"🤖 Ollama Model: {OLLAMA_MODEL}")
    print(f"💾 Database: {DB_PATH}")
    print("Visit http://localhost:5000")
    app.run(debug=True, port=5000)
