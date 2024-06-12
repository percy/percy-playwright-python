# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access]
import json
import unittest
from unittest.mock import MagicMock, patch
from percy.cache import Cache
from percy.page_metadata import PageMetaData


class TestPageMetaData(unittest.TestCase):
    @patch("percy.cache.Cache.get_cache")
    @patch("percy.cache.Cache.set_cache")
    def test_page_metadata(self, mock_set_cache, mock_get_cache):
        # Mock the page and its properties
        page = MagicMock()
        page._impl_obj._guid = "page-guid"
        page.main_frame._impl_obj._guid = "frame-guid"
        page.context.browser._impl_obj._guid = "browser-guid"
        page.evaluate.return_value = json.dumps({"hashed_id": "session-id"})

        # Set up the mocks
        mock_get_cache.return_value = None

        # Create an instance of PageMetaData
        page_metadata = PageMetaData(page)

        # Test framework property
        self.assertEqual(page_metadata.framework, "playwright")

        # Test page_guid property
        self.assertEqual(page_metadata.page_guid, "page-guid")

        # Test frame_guid property
        self.assertEqual(page_metadata.frame_guid, "frame-guid")

        # Test browser_guid property
        self.assertEqual(page_metadata.browser_guid, "browser-guid")

        # Test session_details property when cache is empty
        self.assertEqual(page_metadata.session_details, {"hashed_id": "session-id"})
        mock_set_cache.assert_called_once_with(
            "browser-guid", Cache.session_details, {"hashed_id": "session-id"}
        )

        # Test session_details property when cache is not empty
        mock_get_cache.return_value = {"hashed_id": "cached-session-id"}
        self.assertEqual(
            page_metadata.session_details, {"hashed_id": "cached-session-id"}
        )

        # Test automate_session_id property
        self.assertEqual(page_metadata.automate_session_id, "cached-session-id")
