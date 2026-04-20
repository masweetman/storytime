import tempfile
import unittest
from pathlib import Path

import app as storytime_app


class StoryLimitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)

        self.original_db_path = storytime_app.DB_PATH
        self.original_images_dir = storytime_app.IMAGES_DIR
        self.original_audio_dir = storytime_app.AUDIO_DIR

        storytime_app.DB_PATH = self.temp_path / 'storytime.db'
        storytime_app.IMAGES_DIR = self.temp_path / 'images'
        storytime_app.AUDIO_DIR = self.temp_path / 'audio'

        storytime_app.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        storytime_app.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

        storytime_app.init_db()
        storytime_app.apply_migrations()

        self.client = storytime_app.app.test_client()

    def tearDown(self):
        storytime_app.DB_PATH = self.original_db_path
        storytime_app.IMAGES_DIR = self.original_images_dir
        storytime_app.AUDIO_DIR = self.original_audio_dir
        self.tempdir.cleanup()

    def test_saving_story_prunes_oldest_story_and_files(self):
        storytime_app.set_setting('story_limit', '1')

        oldest_image = storytime_app.IMAGES_DIR / 'oldest.png'
        oldest_audio = storytime_app.AUDIO_DIR / 'oldest.mp3'
        oldest_image.write_bytes(b'old-image')
        oldest_audio.write_bytes(b'old-audio')

        oldest_story_id = storytime_app.save_story(
            character='dragon',
            setting='forest',
            colour='blue',
            story_text='Old story',
            image_path='/images/oldest.png',
            audio_path='/audio/oldest.mp3',
        )

        newest_story_id = storytime_app.save_story(
            character='robot',
            setting='space',
            colour='red',
            story_text='New story',
            image_path='/images/newest.png',
        )

        self.assertIsNone(storytime_app.get_story_by_id(oldest_story_id))
        self.assertIsNotNone(storytime_app.get_story_by_id(newest_story_id))
        self.assertFalse(oldest_image.exists())
        self.assertFalse(oldest_audio.exists())
        self.assertEqual(len(storytime_app.get_all_stories()), 1)

    def test_lowering_story_limit_via_settings_prunes_existing_stories(self):
        first_image = storytime_app.IMAGES_DIR / 'first.png'
        second_image = storytime_app.IMAGES_DIR / 'second.png'
        first_image.write_bytes(b'first-image')
        second_image.write_bytes(b'second-image')

        oldest_story_id = storytime_app.save_story(
            character='bunny',
            setting='meadow',
            colour='yellow',
            story_text='First story',
            image_path='/images/first.png',
        )
        newest_story_id = storytime_app.save_story(
            character='owl',
            setting='treehouse',
            colour='green',
            story_text='Second story',
            image_path='/images/second.png',
        )

        response = self.client.post('/api/settings', json={'story_limit': 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(storytime_app.get_setting('story_limit'), '1')
        self.assertIsNone(storytime_app.get_story_by_id(oldest_story_id))
        self.assertIsNotNone(storytime_app.get_story_by_id(newest_story_id))
        self.assertFalse(first_image.exists())
        self.assertTrue(second_image.exists())


if __name__ == '__main__':
    unittest.main()