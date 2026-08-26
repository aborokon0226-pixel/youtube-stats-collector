"""'노출 클릭율'(썸네일 클릭율) 데이터를 받기 위한 대량 리포트(Reach Report)를 신청한다.

유튜브 Analytics API(실시간 조회)에는 이 지표가 없고, YouTube Reporting API라는
별도의 "신청 -> 며칠 후 파일로 받기" 방식의 API에만 있다. 이 스크립트는 그 신청만 하고,
실제 리포트 파일은 며칠 뒤 download_reach_report.py로 받아온다.

한 번만 실행하면 된다 (이미 신청되어 있으면 다시 신청하지 않는다).
"""

import sys

from googleapiclient.discovery import build

from analyze_linkage import get_oauth_credentials

REACH_REPORT_TYPE_ID = "channel_reach_basic_a1"


def find_existing_reach_job(reporting, report_type_id: str) -> dict | None:
    """이미 신청된 같은 종류의 리포트 작업이 있는지 찾는다."""
    response = reporting.jobs().list().execute()
    for job in response.get("jobs", []):
        if job.get("reportTypeId") == report_type_id:
            return job
    return None


def create_reach_job(reporting, report_type_id: str) -> dict:
    """리포트 작업을 새로 신청한다."""
    return (
        reporting.jobs()
        .create(body={"reportTypeId": report_type_id, "name": "youtube-stats-collector reach report"})
        .execute()
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    creds = get_oauth_credentials()
    reporting = build("youtubereporting", "v1", credentials=creds)

    existing_job = find_existing_reach_job(reporting, REACH_REPORT_TYPE_ID)
    if existing_job:
        print(f"이미 신청되어 있어요. (작업 ID: {existing_job['id']}, 신청일: {existing_job.get('createTime')})")
        print("며칠 뒤 download_reach_report.py로 리포트를 받아올 수 있어요.")
        return

    job = create_reach_job(reporting, REACH_REPORT_TYPE_ID)
    print(f"신청 완료! (작업 ID: {job['id']})")
    print("보통 며칠 후에 첫 리포트가 생성돼요. 나중에 download_reach_report.py로 받아오면 됩니다.")


if __name__ == "__main__":
    main()
