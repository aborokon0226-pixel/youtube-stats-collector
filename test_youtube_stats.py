import unittest

from youtube_stats import dedupe_ids, extract_video_id


class TestExtractVideoId(unittest.TestCase):
    def test_standard_watch_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_shorts_url(self):
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_url_with_extra_params(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_invalid_url_returns_none(self):
        url = "https://www.example.com/not-a-youtube-link"
        self.assertIsNone(extract_video_id(url))


class TestDedupeIds(unittest.TestCase):
    def test_removes_duplicates_preserving_order(self):
        ids = ["a", "b", "a", "c", "b"]
        self.assertEqual(dedupe_ids(ids), ["a", "b", "c"])

    def test_no_duplicates_returns_same_list(self):
        ids = ["a", "b", "c"]
        self.assertEqual(dedupe_ids(ids), ["a", "b", "c"])

    def test_empty_list(self):
        self.assertEqual(dedupe_ids([]), [])


if __name__ == "__main__":
    unittest.main()
