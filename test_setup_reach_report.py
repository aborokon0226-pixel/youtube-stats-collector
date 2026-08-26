import unittest

from setup_reach_report import find_existing_reach_job


class _FakeJobsRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeReportingClient:
    def __init__(self, jobs):
        self._jobs = jobs

    def jobs(self):
        return self

    def list(self):
        return _FakeJobsRequest({"jobs": self._jobs})


class TestFindExistingReachJob(unittest.TestCase):
    def test_finds_matching_job(self):
        reporting = _FakeReportingClient(
            [
                {"id": "job1", "reportTypeId": "other_report"},
                {"id": "job2", "reportTypeId": "channel_reach_basic_a1"},
            ]
        )
        result = find_existing_reach_job(reporting, "channel_reach_basic_a1")
        self.assertEqual(result["id"], "job2")

    def test_returns_none_when_no_match(self):
        reporting = _FakeReportingClient([{"id": "job1", "reportTypeId": "other_report"}])
        self.assertIsNone(find_existing_reach_job(reporting, "channel_reach_basic_a1"))

    def test_returns_none_when_no_jobs(self):
        reporting = _FakeReportingClient([])
        self.assertIsNone(find_existing_reach_job(reporting, "channel_reach_basic_a1"))


if __name__ == "__main__":
    unittest.main()
