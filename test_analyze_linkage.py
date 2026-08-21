import unittest

from analyze_linkage import compute_linkage_rate, fetch_related_video_traffic


class TestComputeLinkageRate(unittest.TestCase):
    def test_sums_only_matching_pulling_sources(self):
        source_views = {"pull_1": 100, "pull_2": 50, "other_channel_video": 999}
        pulling_ids = {"pull_1", "pull_2"}
        linkage_views, rate = compute_linkage_rate(source_views, pulling_ids, pulling_total_views=1000)
        self.assertEqual(linkage_views, 150)
        self.assertAlmostEqual(rate, 15.0)

    def test_zero_pulling_views_returns_zero_rate(self):
        linkage_views, rate = compute_linkage_rate({}, set(), pulling_total_views=0)
        self.assertEqual(linkage_views, 0)
        self.assertEqual(rate, 0.0)

    def test_no_matching_sources(self):
        source_views = {"unrelated": 500}
        linkage_views, rate = compute_linkage_rate(source_views, {"pull_1"}, pulling_total_views=200)
        self.assertEqual(linkage_views, 0)
        self.assertEqual(rate, 0.0)


class _FakeAnalyticsRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeAnalyticsClient:
    def __init__(self, response):
        self._response = response

    def reports(self):
        return self

    def query(self, **kwargs):
        return _FakeAnalyticsRequest(self._response)


class TestFetchRelatedVideoTraffic(unittest.TestCase):
    def test_builds_source_to_views_map(self):
        analytics = _FakeAnalyticsClient({"rows": [["vid_a", 30], ["vid_b", 10]]})
        result = fetch_related_video_traffic(analytics, "key_video")
        self.assertEqual(result, {"vid_a": 30, "vid_b": 10})

    def test_no_rows_returns_empty_dict(self):
        analytics = _FakeAnalyticsClient({})
        result = fetch_related_video_traffic(analytics, "key_video")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
