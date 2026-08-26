import unittest
from datetime import date

from download_reach_report import compute_thumbnail_ctr, list_reports_in_range


class TestComputeThumbnailCtr(unittest.TestCase):
    def test_weighted_ctr_across_matching_rows(self):
        rows = [
            {"video_id": "vid_a", "video_thumbnail_impressions": "1000", "video_thumbnail_impressions_ctr": "0.05"},
            {"video_id": "vid_b", "video_thumbnail_impressions": "500", "video_thumbnail_impressions_ctr": "0.10"},
            {"video_id": "other", "video_thumbnail_impressions": "9999", "video_thumbnail_impressions_ctr": "0.99"},
        ]
        impressions, ctr = compute_thumbnail_ctr(rows, {"vid_a", "vid_b"})
        self.assertEqual(impressions, 1500)
        # (1000*0.05 + 500*0.10) / 1500 * 100 = 100/1500*100
        self.assertAlmostEqual(ctr, 100 / 1500 * 100)

    def test_no_matching_rows_returns_zero(self):
        rows = [{"video_id": "other", "video_thumbnail_impressions": "1000", "video_thumbnail_impressions_ctr": "0.05"}]
        impressions, ctr = compute_thumbnail_ctr(rows, {"vid_a"})
        self.assertEqual(impressions, 0)
        self.assertEqual(ctr, 0.0)

    def test_empty_rows(self):
        impressions, ctr = compute_thumbnail_ctr([], {"vid_a"})
        self.assertEqual(impressions, 0)
        self.assertEqual(ctr, 0.0)


class _FakeReportsRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeReportingClientForReports:
    def __init__(self, reports):
        self._reports = reports

    def jobs(self):
        return self

    def reports(self):
        return self

    def list(self, jobId):
        return _FakeReportsRequest({"reports": self._reports})


class TestListReportsInRange(unittest.TestCase):
    def test_filters_reports_overlapping_range(self):
        reporting = _FakeReportingClientForReports(
            [
                {"id": "r1", "startTime": "2026-08-15T00:00:00Z", "endTime": "2026-08-16T00:00:00Z"},
                {"id": "r2", "startTime": "2026-08-25T00:00:00Z", "endTime": "2026-08-26T00:00:00Z"},
            ]
        )
        result = list_reports_in_range(reporting, "job1", date(2026, 8, 15), date(2026, 8, 21))
        self.assertEqual([r["id"] for r in result], ["r1"])

    def test_no_reports_returns_empty(self):
        reporting = _FakeReportingClientForReports([])
        result = list_reports_in_range(reporting, "job1", date(2026, 8, 15), date(2026, 8, 21))
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
