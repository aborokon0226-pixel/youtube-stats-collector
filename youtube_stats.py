"""유튜브 영상 링크를 입력받아, 주차별 콘텐츠 마케팅 퍼널 표에 조회수를 채워 넣는다."""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build
from openpyxl import Workbook, load_workbook

VIDEO_ID_PATTERNS = [
    r"(?:v=|/videos/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
]

REPORT_PATH = "funnel_report.xlsx"
MAIN_SHEET_NAME = "퍼널 현황"
DETAIL_SHEET_NAME = "상세 내역"

# 사용자가 공유해준 주차별 콘텐츠 마케팅 퍼널 표와 같은 순서.
FUNNEL_ROWS = [
    "매출",
    "객단가",
    "필요고객수",
    "유료회원 전환율",
    "무료회원수",
    "무료회원 전환율",
    "랜딩페이지 접속수",
    "링크클릭율",
    "키콘텐츠 조회수",
    "클릭율",
    "시청지속시간",
    "검색 유입",
    "페이지 유입",
    "키 콘텐츠 연계율",
    "풀링 콘텐츠 조회수",
    "클릭율",
    "시청지속시간",
    "탐색 유입",
    "월간 구독 증가수",
    "구독전환율",
    "하루 평균 조회수",
    "48시간 조회수",
]

# openpyxl은 1부터 시작하고, 1행은 헤더이므로 목록 순서 + 2.
KEY_CONTENT_VIEWS_ROW = FUNNEL_ROWS.index("키콘텐츠 조회수") + 2
PULLING_CONTENT_VIEWS_ROW = FUNNEL_ROWS.index("풀링 콘텐츠 조회수") + 2

FIRST_WEEK_COLUMN = 3  # A=항목, B=월간 목표, C=1주차 현황...


def extract_video_id(url: str) -> str | None:
    """유튜브 URL(일반/단축/shorts)에서 video ID를 추출한다. 실패 시 None."""
    for pattern in VIDEO_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def dedupe_ids(video_ids: list[str]) -> list[str]:
    """순서를 유지하면서 중복된 video ID를 제거한다."""
    seen = set()
    deduped = []
    for video_id in video_ids:
        if video_id not in seen:
            seen.add(video_id)
            deduped.append(video_id)
    return deduped


def fetch_video_stats(youtube, video_ids: list[str]) -> list[dict]:
    """video ID 목록에 대해 유튜브 API로 통계를 조회한다."""
    results = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        response = (
            youtube.videos()
            .list(part="snippet,statistics", id=",".join(batch))
            .execute()
        )
        for item in response.get("items", []):
            stats = item["statistics"]
            snippet = item["snippet"]
            results.append(
                {
                    "video_id": item["id"],
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                }
            )
    return results


def parse_channel_reference(text: str) -> dict:
    """채널 URL/@핸들/채널 ID를 유튜브 API가 이해하는 형태로 바꾼다."""
    text = text.strip()
    match = re.search(r"youtube\.com/channel/([A-Za-z0-9_-]+)", text)
    if match:
        return {"id": match.group(1)}
    match = re.search(r"youtube\.com/@([A-Za-z0-9_.-]+)", text)
    if match:
        return {"forHandle": "@" + match.group(1)}
    if text.startswith("@"):
        return {"forHandle": text}
    if text.startswith("UC") and len(text) == 24:
        return {"id": text}
    return {"forHandle": "@" + text}


def get_uploads_playlist_id(youtube, channel_ref: dict) -> str:
    """채널의 '업로드 전체' 재생목록 ID를 가져온다."""
    response = youtube.channels().list(part="contentDetails", **channel_ref).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError("채널을 찾을 수 없습니다. 채널 주소를 다시 확인해주세요.")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_all_playlist_video_ids(youtube, playlist_id: str) -> list[str]:
    """재생목록에 있는 모든 영상 ID를 페이지를 넘기며 가져온다."""
    video_ids = []
    page_token = None
    while True:
        response = (
            youtube.playlistItems()
            .list(part="contentDetails", playlistId=playlist_id, maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def links_to_video_ids(links: list[str]) -> tuple[list[str], list[str]]:
    """링크 목록을 (유효한 video ID 목록, 인식 못한 링크 목록)으로 나눈다."""
    video_ids = []
    invalid_links = []
    for link in links:
        video_id = extract_video_id(link)
        if video_id:
            video_ids.append(video_id)
        else:
            invalid_links.append(link)
    return dedupe_ids(video_ids), invalid_links


def week_column_index(week: int) -> int:
    """몇 주차인지를 엑셀 열 번호로 변환한다. (1주차 -> C열=3)"""
    return FIRST_WEEK_COLUMN + (week - 1)


def get_or_create_workbook(path: str) -> Workbook:
    """기존 리포트 파일이 있으면 불러오고, 없으면 표 틀을 새로 만든다."""
    if Path(path).exists():
        return load_workbook(path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = MAIN_SHEET_NAME
    sheet.cell(row=1, column=1, value="")
    sheet.cell(row=1, column=2, value="월간 목표")
    for row_index, label in enumerate(FUNNEL_ROWS, start=2):
        sheet.cell(row=row_index, column=1, value=label)
    workbook.create_sheet(DETAIL_SHEET_NAME)
    return workbook


def ensure_week_column(sheet, week: int) -> int:
    """해당 주차의 열이 없으면 헤더를 추가하고, 열 번호를 반환한다."""
    column = week_column_index(week)
    header_cell = sheet.cell(row=1, column=column)
    if not header_cell.value:
        header_cell.value = f"{week}주차 현황"
    return column


def write_view_counts(sheet, week_col: int, key_content_views: int, pulling_content_views: int) -> None:
    sheet.cell(row=KEY_CONTENT_VIEWS_ROW, column=week_col, value=key_content_views)
    sheet.cell(row=PULLING_CONTENT_VIEWS_ROW, column=week_col, value=pulling_content_views)


def write_detail_sheet(workbook: Workbook, week: int, key_rows: list[dict], pulling_rows: list[dict]) -> None:
    """이번 주차에 수집한 영상별 상세 통계를 참고용으로 남긴다."""
    sheet = workbook[DETAIL_SHEET_NAME] if DETAIL_SHEET_NAME in workbook.sheetnames else workbook.create_sheet(DETAIL_SHEET_NAME)
    if sheet.max_row == 1 and sheet.cell(row=1, column=1).value is None:
        sheet.append(["주차", "분류", "제목", "게시일", "조회수", "좋아요수", "댓글수", "영상 링크"])
    for row in key_rows:
        sheet.append([week, "키콘텐츠", row["title"], row["published_at"], row["view_count"], row["like_count"], row["comment_count"], f"https://youtu.be/{row['video_id']}"])
    for row in pulling_rows:
        sheet.append([week, "풀링 콘텐츠", row["title"], row["published_at"], row["view_count"], row["like_count"], row["comment_count"], f"https://youtu.be/{row['video_id']}"])


def read_links_from_stdin(prompt: str) -> list[str]:
    print(prompt)
    links = []
    while True:
        line = input().strip()
        if not line:
            break
        links.append(line)
    return links


def prompt_week_number() -> int:
    while True:
        raw = input("몇 주차 데이터인가요? (숫자만 입력, 예: 1): ").strip()
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print("1 이상의 숫자를 입력해주세요.")


def collect_stats(youtube, links: list[str]) -> list[dict]:
    video_ids, invalid_links = links_to_video_ids(links)
    if invalid_links:
        print("다음 링크에서는 영상 ID를 찾을 수 없어 제외했습니다:")
        for link in invalid_links:
            print(f"  - {link}")
    if not video_ids:
        return []
    return fetch_video_stats(youtube, video_ids)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("오류: YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    week = prompt_week_number()
    key_links = read_links_from_stdin(
        "[키콘텐츠] 랜딩페이지로 유입시키는 영상 링크를 한 줄에 하나씩 입력하세요. 없으면 바로 Enter."
    )
    channel_text = input(
        "[풀링 콘텐츠] 채널 전체에서 자동으로 계산합니다. 채널 주소(@핸들 또는 channel/UC... URL)를 입력하세요: "
    ).strip()

    youtube = build("youtube", "v3", developerKey=api_key)
    key_rows = collect_stats(youtube, key_links)
    key_video_ids = {row["video_id"] for row in key_rows}

    pulling_rows = []
    if channel_text:
        uploads_playlist_id = get_uploads_playlist_id(youtube, parse_channel_reference(channel_text))
        all_video_ids = get_all_playlist_video_ids(youtube, uploads_playlist_id)
        pulling_video_ids = [video_id for video_id in all_video_ids if video_id not in key_video_ids]
        pulling_rows = fetch_video_stats(youtube, pulling_video_ids)

    key_views = sum(row["view_count"] for row in key_rows)
    pulling_views = sum(row["view_count"] for row in pulling_rows)

    workbook = get_or_create_workbook(REPORT_PATH)
    sheet = workbook[MAIN_SHEET_NAME]
    week_col = ensure_week_column(sheet, week)
    write_view_counts(sheet, week_col, key_views, pulling_views)
    write_detail_sheet(workbook, week, key_rows, pulling_rows)
    workbook.save(REPORT_PATH)

    print(f"완료: {week}주차 - 키콘텐츠 조회수 {key_views}, 풀링 콘텐츠 조회수 {pulling_views}")
    print(f"{REPORT_PATH} 파일에 저장했습니다. (아직 자동으로 못 채우는 항목은 직접 입력해주세요)")


if __name__ == "__main__":
    main()
