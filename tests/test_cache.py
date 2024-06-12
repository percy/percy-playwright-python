# . # pylint: disable=[arguments-differ, protected-access]
import time
import unittest
from unittest.mock import patch
from percy.cache import Cache


class TestCache(unittest.TestCase):
    def setUp(self) -> None:
        self.cache = Cache
        self.session_id = "session_id_123"
        self.session_details = {
            "browser": "chrome",
            "platform": "windows",
            "browserVersion": "115.0.1",
            "hashed_id": "abcdef",
        }

        self.cache.set_cache(
            self.session_id, Cache.session_details, self.session_details
        )
        self.cache.set_cache(self.session_id, "key-1", "some-value")

    def test_set_cache(self):
        with self.assertRaises(Exception) as e:
            self.cache.set_cache(123, 123, 123)
        self.assertEqual(str(e.exception), "Argument session_id should be string")

        with self.assertRaises(Exception) as e:
            self.cache.set_cache(self.session_id, 123, 123)
        self.assertEqual(str(e.exception), "Argument property should be string")

        self.assertIn(self.session_id, self.cache.CACHE)
        self.assertDictEqual(
            self.cache.CACHE[self.session_id][Cache.session_details],
            self.session_details,
        )

    def test_get_cache_invalid_args(self):
        with self.assertRaises(Exception) as e:
            self.cache.get_cache(123, 123)
        self.assertEqual(str(e.exception), "Argument session_id should be string")

        with self.assertRaises(Exception) as e:
            self.cache.get_cache(self.session_id, 123)
        self.assertEqual(str(e.exception), "Argument property should be string")

    @patch.object(Cache, "cleanup_cache")
    def test_get_cache_success(self, mock_cleanup_cache):
        session_details = self.cache.get_cache(self.session_id, Cache.session_details)
        self.assertDictEqual(session_details, self.session_details)
        mock_cleanup_cache.assert_called()

    @patch("percy.cache.Cache.CACHE_TIMEOUT", 1)
    def test_cleanup_cache(self):
        cache_timeout = self.cache.CACHE_TIMEOUT
        time.sleep(cache_timeout + 1)
        self.assertIn(self.session_id, self.cache.CACHE)
        self.assertIn("key-1", self.cache.CACHE[self.session_id])
        self.cache.cleanup_cache()
        self.assertIn(self.session_id, self.cache.CACHE)
        self.assertIn("session_details", self.cache.CACHE[self.session_id])
        self.assertNotIn("key-1", self.cache.CACHE[self.session_id])
