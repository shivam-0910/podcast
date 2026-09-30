import unittest
from pathlib import Path

from config.config import Config
from services import episode_service


class EpisodePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = Config.DATABASE_PATH
        self.test_db_path = Path(__file__).resolve().parent.parent / "data" / "test_podcast.db"
        Config.DATABASE_PATH = self.test_db_path
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        episode_service._store.clear()
        episode_service.init_storage()

    def tearDown(self):
        Config.DATABASE_PATH = self.original_db_path
        episode_service._store.clear()

    def test_persisted_episode_is_loaded_after_restart(self):
        episode = {
            "episode_id": "1234567890abcdef1234567890abcdef",
            "title": "Test title",
            "topic": "AI",
            "language": "en",
            "voices": {"host_a": "voice-a", "host_b": "voice-b"},
            "conversation": [
                {"id": 1, "speaker": "host_a", "text": "Hello there", "audio_url": "/audio/123/001_host_a.wav"},
                {"id": 2, "speaker": "host_b", "text": "Hi there", "audio_url": "/audio/123/002_host_b.wav"},
            ],
        }

        episode_service._remember(episode)
        episode_service._persist_episode(episode)
        episode_service._store.clear()

        loaded = episode_service.get_episode(episode["episode_id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], "Test title")
        self.assertEqual(loaded["conversation"][1]["speaker"], "host_b")


if __name__ == "__main__":
    unittest.main()
