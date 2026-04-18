from flask import Flask, render_template, request, jsonify
import requests
import re
import os
from dotenv import load_dotenv
from pathlib import Path
import sqlite3
from contextlib import contextmanager

load_dotenv()

app = Flask(__name__)

# Database configuration
DB_PATH = Path(__file__).parent / 'settings.db'

# Image configuration
IMAGES_DIR = Path(__file__).parent / 'static' / 'images'
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
    """Initialize database with settings table"""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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

# Initialize database on startup
init_db()

# Ollama configuration - read from database
OLLAMA_HOST = get_setting('ollama_host', 'http://localhost:11434')
OLLAMA_MODEL = get_setting('ollama_model', 'gemma2:2b')

# Ollama configuration - read from database
OLLAMA_HOST = get_setting('ollama_host', 'http://localhost:11434')
OLLAMA_MODEL = get_setting('ollama_model', 'gemma2:2b')
OLLAMA_API = f"{OLLAMA_HOST}/api/generate"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/story')
def story():
    return render_template('story.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings"""
    return jsonify(get_all_settings())

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update settings"""
    data = request.json
    
    # Validate and save settings
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
    
    return jsonify({
        'success': True,
        'message': 'Settings updated successfully'
    })

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current Ollama configuration"""
    return jsonify({
        'ollama_host': OLLAMA_HOST,
        'ollama_model': OLLAMA_MODEL
    })

@app.route('/api/config', methods=['POST'])
def set_config():
    """Update Ollama configuration"""
    global OLLAMA_HOST, OLLAMA_API
    data = request.json
    new_host = data.get('ollama_host', OLLAMA_HOST).rstrip('/')
    
    # Validate the connection
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
            return jsonify({
                'success': False,
                'error': 'Ollama server returned an error'
            }), 500
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'error': 'Cannot connect to Ollama at that address'
        }), 500
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)}'
        }), 500

def download_and_save_image(prompt, image_num):
    """Download image from Pollinations.ai and save locally"""
    try:
        print(f"📥 Downloading image {image_num} from Pollinations.ai...")
        print(f"   Prompt: {prompt[:60]}...")
        
        # URL-encode the prompt
        encoded_prompt = requests.utils.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        
        # Download the image (can take 30-60+ seconds for generation)
        print(f"   Waiting for Pollinations.ai to generate image {image_num}...")
        response = requests.get(image_url, timeout=120)
        
        print(f"   Response status: {response.status_code}, size: {len(response.content)} bytes")
        
        if response.status_code == 200:
            # Save as PNG
            image_path = IMAGES_DIR / f"img-{image_num}.png"
            with open(image_path, 'wb') as f:
                f.write(response.content)
            print(f"✅ Saved image {image_num} ({len(response.content)} bytes) to {image_path}")
            return f"/static/images/img-{image_num}.png"
        else:
            print(f"⚠️  Failed to download image {image_num}: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return None
            
    except requests.exceptions.Timeout:
        print(f"⚠️  Timeout downloading image {image_num} - Pollinations.ai took too long")
        return None
    except Exception as e:
        print(f"⚠️  Error downloading image {image_num}: {type(e).__name__}: {e}")
        return None

@app.route('/api/generate-story', methods=['POST'])
def generate_story():
    """Generate a story using Ollama based on user selections"""
    data = request.json
    character = data.get('character', 'dragon')
    setting = data.get('setting', 'forest')
    colour = data.get('colour', 'blue')
    
    # Create the prompt using the custom template from settings
    prompt_template = get_setting('story_prompt', DEFAULT_SETTINGS['story_prompt'])
    prompt = prompt_template.format(character=character, setting=setting, colour=colour)
    
    try:
        print(f"📝 Generating story with model: {OLLAMA_MODEL}")
        print(f"📡 Using Ollama at: {OLLAMA_HOST}")
        
        # Call Ollama
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
            
            # Generate image URLs using picsum.photos (simple, reliable, no API needed)
            # Each request gets a different random image
            image_urls = []
            for index in range(3):
                # picsum.photos returns random images, simple and works great with img tags
                img_url = f"https://picsum.photos/600/400?random={index}&t={int(__import__('time').time())}"
                image_urls.append(img_url)
            
            print(f"✅ Story generated successfully ({len(story_text)} chars)")
            
            # Generate a single image for the story using Pollinations.ai
            image_prompt = f"{character} in a {colour} {setting}, bedtime story illustration, cute cartoon style"
            
            img_url = download_and_save_image(image_prompt, 1)
            image_urls = [img_url] if img_url else ["/static/images/img-1.png"]
            
            return jsonify({
                'success': True,
                'story': story_text,
                'images': image_urls,
                'character': character,
                'setting': setting,
                'colour': colour
            })
            
            return jsonify({
                'success': True,
                'story': story_text,
                'images': image_urls,
                'character': character,
                'setting': setting,
                'colour': colour
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
    print("Visit http://localhost:5000")
    print("⚙️  Click the settings icon to change Ollama address if needed")
    app.run(debug=True, port=5000)
