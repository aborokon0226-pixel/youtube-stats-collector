"""유튜브 영상 링크를 입력받아, 주차별 콘텐츠 마케팅 퍼널 표에 조회수를 채워 넣는다."""

import calendar
import os
import re
import sys
from datetime import date
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
SUBSCRIBER_SNAPSHOT_SHEET = "구독자 스냅샷"

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
    "외부 유입",
    "키 콘텐츠 연계율",
    "풀링 콘텐츠 조회수",
    "클릭율",
    "시청지속시간",
    "탐색 유입",
    "외부 유입",
    "월간 구독 증가수",
    "구독전환율",
    "하루 평균 조회수",
    "48시간 조회수",
]

# openpyxl은 1부터 시작하고, 1행은 헤더이므로 목록 순서 + 2.
KEY_CONTENT_VIEWS_ROW = FUNNEL_ROWS.index("키콘텐츠 조회수") + 2
PULLING_CONTENT_VIEWS_ROW = FUNNEL_ROWS.index("풀링 콘텐츠 조회수") + 2
SUBSCRIBER_GROWTH_ROW = FUNNEL_ROWS.index("월간 구독 증가수") + 2
SUBSCRIBER_CONVERSION_ROW = FUNNEL_ROWS.index("구독전환율") + 2
DAILY_AVERAGE_VIEWS_ROW = FUNNEL_ROWS.index("하루 평균 조회수") + 2
FORTY_EIGHT_HOUR_VIEWS_ROW = FUNNEL_ROWS.index("48시간 조회수") + 2

# "클릭율"/"시청지속시간"/"외부 유입"은 키콘텐츠·풀링 콘텐츠 구간에 각각 한 번씩 등장해서 위치로 구분한다.
# "클릭율"(노출 대비 클릭)은 실시간 Analytics API가 아니라, 별도 신청이 필요한
# YouTube Reporting API의 리치 리포트로만 받을 수 있다 (setup_reach_report.py / download_reach_report.py).
KEY_CTR_ROW = 11
KEY_AVG_VIEW_DURATION_ROW = 12
SEARCH_TRAFFIC_ROW = 13
PAGE_TRAFFIC_ROW = 14
EXT_TRAFFIC_KEY_ROW = 15
PULLING_CTR_ROW = 18
PULLING_AVG_VIEW_DURATION_ROW = 19
BROWSE_TRAFFIC_ROW = 20
EXT_TRAFFIC_PULLING_ROW = 21

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


def fetch_channel_subscriber_count(youtube, channel_ref: dict) -> int:
    """채널의 현재 구독자 수(공개 데이터)를 가져온다."""
    response = youtube.channels().list(part="statistics", **channel_ref).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError("채널을 찾을 수 없습니다. 채널 주소를 다시 확인해주세요.")
    return int(items[0]["statistics"].get("subscriberCount", 0))


def get_channel_id(youtube, channel_ref: dict) -> str:
    """채널의 고유 ID(UC...)를 가져온다. 채널을 바꿔도 스냅샷 기록을 구분하는 데 쓴다."""
    response = youtube.channels().list(part="id", **channel_ref).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError("채널을 찾을 수 없습니다. 채널 주소를 다시 확인해주세요.")
    return items[0]["id"]


def get_previous_subscriber_snapshot(workbook: Workbook, week: int, channel_id: str) -> int | None:
    """같은 채널의 기록 중, week보다 이전 주차에서 가장 최근 구독자 수 스냅샷을 찾는다.

    채널을 바꾼 뒤에도 예전 채널의 스냅샷과 잘못 비교하지 않도록, 채널 ID가 같은 행만 본다."""
    if SUBSCRIBER_SNAPSHOT_SHEET not in workbook.sheetnames:
        return None
    sheet = workbook[SUBSCRIBER_SNAPSHOT_SHEET]
    best: tuple[int, int] | None = None
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        snapshot_week, subscriber_count = row[0], row[1]
        row_channel_id = row[2] if len(row) > 2 else None
        if row_channel_id != channel_id:
            continue
        if snapshot_week < week and (best is None or snapshot_week > best[0]):
            best = (snapshot_week, subscriber_count)
    return best[1] if best else None


def record_subscriber_snapshot(workbook: Workbook, week: int, subscriber_count: int, channel_id: str) -> None:
    """이번 주차의 구독자 수를 채널 ID와 함께 기록해서, 다음 주에 증가분을 계산할 수 있게 남겨둔다."""
    sheet = (
        workbook[SUBSCRIBER_SNAPSHOT_SHEET]
        if SUBSCRIBER_SNAPSHOT_SHEET in workbook.sheetnames
        else workbook.create_sheet(SUBSCRIBER_SNAPSHOT_SHEET)
    )
    if sheet.max_row == 1 and sheet.max_column == 1:
        sheet.append(["주차", "구독자수", "채널ID"])
    for row_cells in sheet.iter_rows(min_row=2):
        if row_cells[0].value == week and row_cells[2].value == channel_id:
            row_cells[1].value = subscriber_count
            return
    sheet.append([week, subscriber_count, channel_id])


def compute_subscriber_conversion_rate(subscriber_growth: int, total_views: int) -> float:
    """조회수 대비 구독전환율(%)을 계산한다."""
    return (subscriber_growth / total_views * 100) if total_views else 0.0


def compute_daily_average_views(total_views: int) -> float:
    """이번 주(7일) 조회수를 하루 평균으로 환산한다."""
    return total_views / 7


def estimate_48_hour_views(daily_average_views: float) -> float:
    """48시간 조회수는 개별 영상마다 게시 후 정확히 48시간 시점을 봐야 정확하지만,
    아직 그 데이터는 못 가져오므로 하루 평균 조회수의 2배로 추정한다."""
    return daily_average_views * 2


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


def week_of_month(d: date) -> int:
    """그 달에서 몇 번째 7일 구간인지 (1~7일=1주차, 8~14일=2주차, ...)."""
    return (d.day - 1) // 7 + 1


def week_date_range(d: date) -> tuple[date, date]:
    """d가 속한 '주차'의 시작일과 종료일을 구한다. (월 마지막 주는 말일에서 끊김)"""
    week = week_of_month(d)
    start_day = (week - 1) * 7 + 1
    last_day_of_month = calendar.monthrange(d.year, d.month)[1]
    end_day = min(week * 7, last_day_of_month)
    return d.replace(day=start_day), d.replace(day=end_day)


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
    if sheet.max_row == 1 and sheet.max_column == 1:
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
    default_week = week_of_month(date.today())
    while True:
        raw = input(f"몇 주차 데이터인가요? (숫자만 입력, 기본값 {default_week}주차 - 그냥 Enter): ").strip()
        if not raw:
            return default_week
        if raw.isdigit() and int(raw) >= 1:
            return int(raw)
        print("1 이상의 숫자를 입력해주세요.")


def prompt_channel_reference(prompt: str) -> str:
    """DEFAULT_CHANNEL_URL이 .env에 있으면 기본값으로 보여주고, 빈 입력이면 그 값을 쓴다."""
    default = os.environ.get("DEFAULT_CHANNEL_URL", "")
    hint = f" (기본값: {default} - 그냥 Enter)" if default else ""
    raw = input(f"{prompt}{hint}: ").strip()
    return raw or default


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
    channel_text = prompt_channel_reference(
        "[풀링 콘텐츠] 채널 전체에서 자동으로 계산합니다. 채널 주소(@핸들 또는 channel/UC... URL)를 입력하세요"
    )

    youtube = build("youtube", "v3", developerKey=api_key)
    key_rows = collect_stats(youtube, key_links)
    key_video_ids = {row["video_id"] for row in key_rows}

    pulling_rows = []
    subscriber_count = None
    channel_id = None
    if channel_text:
        channel_ref = parse_channel_reference(channel_text)
        uploads_playlist_id = get_uploads_playlist_id(youtube, channel_ref)
        all_video_ids = get_all_playlist_video_ids(youtube, uploads_playlist_id)
        pulling_video_ids = [video_id for video_id in all_video_ids if video_id not in key_video_ids]
        pulling_rows = fetch_video_stats(youtube, pulling_video_ids)
        subscriber_count = fetch_channel_subscriber_count(youtube, channel_ref)
        channel_id = get_channel_id(youtube, channel_ref)

    key_views = sum(row["view_count"] for row in key_rows)
    pulling_views = sum(row["view_count"] for row in pulling_rows)

    workbook = get_or_create_workbook(REPORT_PATH)
    sheet = workbook[MAIN_SHEET_NAME]
    week_col = ensure_week_column(sheet, week)
    write_view_counts(sheet, week_col, key_views, pulling_views)
    write_detail_sheet(workbook, week, key_rows, pulling_rows)

    subscriber_growth = None
    if subscriber_count is not None:
        previous_count = get_previous_subscriber_snapshot(workbook, week, channel_id)
        if previous_count is not None:
            subscriber_growth = subscriber_count - previous_count
            conversion_rate = compute_subscriber_conversion_rate(subscriber_growth, key_views + pulling_views)
            sheet.cell(row=SUBSCRIBER_GROWTH_ROW, column=week_col, value=subscriber_growth)
            sheet.cell(row=SUBSCRIBER_CONVERSION_ROW, column=week_col, value=round(conversion_rate, 2))
        record_subscriber_snapshot(workbook, week, subscriber_count, channel_id)

    daily_average_views = compute_daily_average_views(key_views + pulling_views)
    forty_eight_hour_views = estimate_48_hour_views(daily_average_views)
    sheet.cell(row=DAILY_AVERAGE_VIEWS_ROW, column=week_col, value=round(daily_average_views, 1))
    sheet.cell(row=FORTY_EIGHT_HOUR_VIEWS_ROW, column=week_col, value=round(forty_eight_hour_views, 1))

    workbook.save(REPORT_PATH)

    print(f"완료: {week}주차 - 키콘텐츠 조회수 {key_views}, 풀링 콘텐츠 조회수 {pulling_views}")
    if subscriber_growth is not None:
        print(f"       월간 구독 증가수 {subscriber_growth}명 (현재 구독자 수 {subscriber_count}명)")
    elif subscriber_count is not None:
        print(f"       현재 구독자 수 {subscriber_count}명을 기록했어요. 다음 주부터 증가수가 계산돼요.")
    print(f"       하루 평균 조회수 {daily_average_views:.1f}회, 48시간 조회수(추정) {forty_eight_hour_views:.1f}회")
    print(f"{REPORT_PATH} 파일에 저장했습니다. (아직 자동으로 못 채우는 항목은 직접 입력해주세요)")


if __name__ == "__main__":
    main()
