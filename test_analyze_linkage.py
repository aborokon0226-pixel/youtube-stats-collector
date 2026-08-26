import unittest

from analyze_linkage import (
    compute_average_view_duration_seconds,
    compute_linkage_rate,
    fetch_related_video_traffic,
    fetch_traffic_source_views,
    fetch_view_duration_stats,
)


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


class _FakePerVideoAnalyticsClient:
    """video_id별로 다른 응답을 주는 스텁 (fetch_traffic_source_views가 영상마다 따로 요청하기 때문)."""

    def __init__(self, responses_by_video_id):
        self._responses = responses_by_video_id
        self.requested_filters = []

    def reports(self):
        return self

    def query(self, **kwargs):
        self.requested_filters.append(kwargs.get("filters"))
        for video_id, response in self._responses.items():
            if f"video=={video_id};" in kwargs.get("filters", ""):
                return _FakeAnalyticsRequest(response)
        return _FakeAnalyticsRequest({})


class TestFetchTrafficSourceViews(unittest.TestCase):
    def test_sums_detail_rows_across_videos(self):
        analytics = _FakePerVideoAnalyticsClient(
            {
                "vid_a": {"rows": [["query one", 20], ["query two", 10]]},
                "vid_b": {"rows": [["query three", 10]]},
            }
        )
        self.assertEqual(fetch_traffic_source_views(analytics, ["vid_a", "vid_b"], "YT_SEARCH"), 40)

    def test_video_with_no_matching_rows_contributes_zero(self):
        analytics = _FakePerVideoAnalyticsClient({"vid_a": {"rows": [["query one", 30]]}, "vid_b": {"rows": []}})
        self.assertEqual(fetch_traffic_source_views(analytics, ["vid_a", "vid_b"], "YT_SEARCH"), 30)

    def test_empty_video_list_skips_request(self):
        analytics = _FakePerVideoAnalyticsClient({"vid_a": {"rows": [["query one", 30]]}})
        self.assertEqual(fetch_traffic_source_views(analytics, [], "YT_SEARCH"), 0)


class TestViewDurationStats(unittest.TestCase):
    def test_sums_views_and_minutes(self):
        analytics = _FakeAnalyticsClient({"rows": [["vid_a", 100, 50.0], ["vid_b", 50, 25.0]]})
        views, minutes = fetch_view_duration_stats(analytics, ["vid_a", "vid_b"])
        self.assertEqual(views, 150)
        self.assertAlmostEqual(minutes, 75.0)

    def test_empty_video_list_returns_zeros(self):
        analytics = _FakeAnalyticsClient({"rows": [["vid_a", 100, 50.0]]})
        self.assertEqual(fetch_view_duration_stats(analytics, []), (0, 0.0))

    def test_average_duration_seconds(self):
        self.assertAlmostEqual(compute_average_view_duration_seconds(total_views=100, total_minutes=50.0), 30.0)

    def test_average_duration_zero_views(self):
        self.assertEqual(compute_average_view_duration_seconds(total_views=0, total_minutes=50.0), 0.0)


if __name__ == "__main__":
    unittest.main()
