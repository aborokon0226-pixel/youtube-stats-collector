"""setup_reach_report.py로 신청해둔 '노출 클릭율'(썸네일 클릭율) 리치 리포트를 받아와서 표에 채운다.

리치 리포트는 하루 단위 파일로 생기고, 보통 신청 후 며칠 뒤부터 받을 수 있다.
아직 리포트가 하나도 없다면 "아직 준비되지 않았어요" 라고 알려주고 끝난다.
"""

import csv
import io
import os
import sys
from datetime import date, datetime

import requests
from dotenv import load_dotenv
from googleapiclient.discovery import build

from analyze_linkage import get_oauth_credentials
from setup_reach_report import REACH_REPORT_TYPE_ID, find_existing_reach_job
from youtube_stats import (
    KEY_CTR_ROW,
    MAIN_SHEET_NAME,
    PULLING_CTR_ROW,
    REPORT_PATH,
    ensure_week_column,
    extract_video_id,
    get_all_playlist_video_ids,
    get_or_create_workbook,
    get_uploads_playlist_id,
    parse_channel_reference,
    prompt_channel_reference,
    prompt_week_number,
    week_date_range,
)


def list_reports_in_range(reporting, job_id: str, start: date, end: date) -> list[dict]:
    """작업에 쌓인 리포트 중, 지정한 기간과 겹치는 것들만 골라낸다."""
    response = reporting.jobs().reports().list(jobId=job_id).execute()
    matched = []
    for report in response.get("reports", []):
        report_start = datetime.fromisoformat(report["startTime"].replace("Z", "+00:00")).date()
        report_end = datetime.fromisoformat(report["endTime"].replace("Z", "+00:00")).date()
        if report_start <= end and report_end >= start:
            matched.append(report)
    return matched


def download_report_rows(creds, download_url: str) -> list[dict]:
    """다운로드 URL의 CSV를 dict 행 목록으로 받아온다."""
    response = requests.get(download_url, headers={"Authorization": f"Bearer {creds.token}"})
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.content.decode("utf-8")))
    return list(reader)


def compute_thumbnail_ctr(rows: list[dict], video_ids: set[str]) -> tuple[int, float]:
    """CSV 행들 중 video_ids에 해당하는 것만 모아서 (총 노출수, 노출 대비 클릭율%) 을 계산한다.

    video_thumbnail_impressions_ctr이 0~1 비율인지 0~100 퍼센트인지는 실제 데이터를 받아봐야
    확실히 알 수 있어서, 우선 0~1 비율로 가정하고 100을 곱한다. 실제 값을 보고 다르면 조정이 필요하다.
    """
    total_impressions = 0
    total_clicks = 0.0
    for row in rows:
        if row.get("video_id") not in video_ids:
            continue
        impressions = int(row.get("video_thumbnail_impressions") or 0)
        ctr_ratio = float(row.get("video_thumbnail_impressions_ctr") or 0)
        total_impressions += impressions
        total_clicks += impressions * ctr_ratio
    ctr_percent = (total_clicks / total_impressions * 100) if total_impressions else 0.0
    return total_impressions, ctr_percent


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("오류: YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    creds = get_oauth_credentials()
    reporting = build("youtubereporting", "v1", credentials=creds)

    job = find_existing_reach_job(reporting, REACH_REPORT_TYPE_ID)
    if not job:
        print("아직 리포트를 신청하지 않았어요. setup_reach_report.py를 먼저 실행해주세요.")
        sys.exit(1)

    week = prompt_week_number()
    default_start, default_end = week_date_range(date.today())
    start_raw = input(f"이번 주 시작일을 입력하세요 (기본값 {default_start.isoformat()} - 그냥 Enter): ").strip()
    end_raw = input(f"이번 주 종료일을 입력하세요 (기본값 {default_end.isoformat()} - 그냥 Enter): ").strip()
    start_date = date.fromisoformat(start_raw) if start_raw else default_start
    end_date = date.fromisoformat(end_raw) if end_raw else default_end

    reports = list_reports_in_range(reporting, job["id"], start_date, end_date)
    if not reports:
        print("이 기간에 해당하는 리포트가 아직 없어요. 신청 후 며칠 더 기다려주세요.")
        sys.exit(0)

    key_link = input("키콘텐츠 링크를 입력하세요: ").strip()
    key_video_id = extract_video_id(key_link)
    channel_text = prompt_channel_reference("채널 주소(@핸들 또는 channel/UC... URL)를 입력하세요")

    youtube = build("youtube", "v3", developerKey=api_key)
    pulling_video_ids: set[str] = set()
    if channel_text:
        channel_ref = parse_channel_reference(channel_text)
        uploads_playlist_id = get_uploads_playlist_id(youtube, channel_ref)
        all_video_ids = get_all_playlist_video_ids(youtube, uploads_playlist_id)
        pulling_video_ids = {video_id for video_id in all_video_ids if video_id != key_video_id}

    all_rows: list[dict] = []
    for report in reports:
        all_rows.extend(download_report_rows(creds, report["downloadUrl"]))

    print(f"참고용 원본 데이터 첫 줄: {all_rows[0] if all_rows else '(없음)'}")

    key_video_ids = {key_video_id} if key_video_id else set()
    key_impressions, key_ctr = compute_thumbnail_ctr(all_rows, key_video_ids)
    pulling_impressions, pulling_ctr = compute_thumbnail_ctr(all_rows, pulling_video_ids)

    workbook = get_or_create_workbook(REPORT_PATH)
    sheet = workbook[MAIN_SHEET_NAME]
    week_col = ensure_week_column(sheet, week)
    sheet.cell(row=KEY_CTR_ROW, column=week_col, value=round(key_ctr, 2))
    sheet.cell(row=PULLING_CTR_ROW, column=week_col, value=round(pulling_ctr, 2))
    workbook.save(REPORT_PATH)

    print(f"완료: {week}주차 - 키콘텐츠 클릭율(노출 대비) {key_ctr:.2f}% (노출수 {key_impressions})")
    print(f"       풀링 콘텐츠 클릭율(노출 대비) {pulling_ctr:.2f}% (노출수 {pulling_impressions})")


if __name__ == "__main__":
    main()
