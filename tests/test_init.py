# pylint: disable=[abstract-class-instantiated, arguments-differ, protected-access]
import unittest
from unittest.mock import patch, MagicMock
import percy


class TestPercyInit(unittest.TestCase):
    @patch("percy.percy_snapshot")
    def test_percySnapshot_wrapper(self, mock_percy_snapshot):
        """Test the percySnapshot backwards compatibility wrapper."""
        mock_page = MagicMock()
        mock_percy_snapshot.return_value = "snapshot_result"

        # Call via percy module to test the wrapper
        # percySnapshot(browser, *a, **kw) calls percy_snapshot(page=browser, *a, **kw)
        result = percy.percySnapshot(mock_page, "test_name", some_option=True)

        # Verify percy_snapshot was called correctly
        # Check that the function was called
        self.assertTrue(mock_percy_snapshot.called)
        # Check page argument and keyword argument
        actual_call = mock_percy_snapshot.call_args
        self.assertEqual(actual_call.kwargs['page'], mock_page)
        self.assertEqual(actual_call.kwargs['some_option'], True)
        self.assertEqual(result, "snapshot_result")

    @patch("percy.percy_automate_screenshot")
    def test_percy_screenshot_wrapper(self, mock_automate_screenshot):
        """Test the percy_screenshot wrapper."""
        mock_page = MagicMock()
        mock_automate_screenshot.return_value = "screenshot_result"

        # Call via percy module to test the wrapper
        result = percy.percy_screenshot(mock_page, "test_name", options={"key": "value"})

        # Verify percy_automate_screenshot was called correctly
        mock_automate_screenshot.assert_called_once_with(
            mock_page, "test_name", options={"key": "value"}
        )
        self.assertEqual(result, "screenshot_result")

    def test_version_imported(self):
        """Test that __version__ is properly imported."""
        self.assertIsNotNone(percy.__version__)
        self.assertIsInstance(percy.__version__, str)


if __name__ == "__main__":
    unittest.main()
