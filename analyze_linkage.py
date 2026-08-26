"""채널 소유자만 볼 수 있는 심화 지표를 계산한다.

- 키 콘텐츠 연계율: 풀링 콘텐츠를 본 사람이 '추천 동영상' 패널을 통해 키콘텐츠로 넘어간 비율
- 시청지속시간, 검색/페이지/탐색 유입: 키콘텐츠·풀링 콘텐츠 각각
  (클릭율/노출수는 유튜브 Analytics API가 제공하지 않아 이 스크립트로는 못 가져온다 — 스튜디오 화면에서만 확인 가능)

API 키가 아니라 구글 로그인(OAuth)이 필요하다.
"""

import os
import sys
import webbrowser
from datetime import date

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from youtube_stats import (
    BROWSE_TRAFFIC_ROW,
    FUNNEL_ROWS,
    KEY_AVG_VIEW_DURATION_ROW,
    MAIN_SHEET_NAME,
    PAGE_TRAFFIC_ROW,
    PULLING_AVG_VIEW_DURATION_ROW,
    REPORT_PATH,
    SEARCH_TRAFFIC_ROW,
    ensure_week_column,
    extract_video_id,
    fetch_video_stats,
    get_all_playlist_video_ids,
    get_or_create_workbook,
    get_uploads_playlist_id,
    parse_channel_reference,
    prompt_channel_reference,
    prompt_week_number,
)

SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]
CLIENT_SECRET_PATH = "client_secret.json"
TOKEN_PATH = "token.json"
AUTH_URL_PATH = "auth_url.txt"

LINKAGE_RATE_ROW = FUNNEL_ROWS.index("키 콘텐츠 연계율") + 2


def get_oauth_credentials() -> Credentials:
    """토큰이 있으면 재사용하고, 없거나 만료됐으면 브라우저 로그인을 새로 진행한다."""
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            print("브라우저가 열리면, 유튜브 채널을 관리하는 구글 계정으로 로그인해주세요.")

            original_open = webbrowser.open

            def open_and_save(url, *args, **kwargs):
                with open(AUTH_URL_PATH, "w", encoding="utf-8") as f:
                    f.write(url)
                print(
                    f"(브라우저가 자동으로 안 열리면, {AUTH_URL_PATH} 파일을 메모장으로 열어서 "
                    "주소 전체를 복사해 브라우저에 붙여넣으세요.)"
                )
                return original_open(url, *args, **kwargs)

            webbrowser.open = open_and_save
            try:
                creds = flow.run_local_server(port=0, timeout_seconds=3600)
            finally:
                webbrowser.open = original_open
        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return creds


def fetch_related_video_traffic(analytics, key_video_id: str) -> dict[str, int]:
    """key_video_id로 '추천 동영상' 패널을 통해 유입된 소스 영상별 조회수를 가져온다."""
    response = (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate="2020-01-01",
            endDate=date.today().isoformat(),
            metrics="views",
            dimensions="insightTrafficSourceDetail",
            filters=f"video=={key_video_id};insightTrafficSourceType==RELATED_VIDEO",
            maxResults=25,
            sort="-views",
        )
        .execute()
    )
    return {row[0]: row[1] for row in response.get("rows", [])}


def compute_linkage_rate(source_views: dict[str, int], pulling_video_ids: set[str], pulling_total_views: int) -> tuple[int, float]:
    """풀링 콘텐츠에서 넘어온 조회수 합과, 풀링 콘텐츠 전체 대비 비율(%)을 계산한다."""
    linkage_views = sum(views for source_id, views in source_views.items() if source_id in pulling_video_ids)
    linkage_rate = (linkage_views / pulling_total_views * 100) if pulling_total_views else 0.0
    return linkage_views, linkage_rate


def fetch_traffic_source_views(analytics, video_ids: list[str], source_type: str) -> int:
    """주어진 영상들에 대해 특정 유입 경로(source_type)로 들어온 조회수 합을 가져온다.

    video 필터와 insightTrafficSourceType 필터를 함께 쓰려면 insightTrafficSourceDetail
    차원이 같이 있어야 하는 리포트 조합이라, 영상 하나씩 조회한 뒤 세부 항목 조회수를 다 더한다."""
    total = 0
    for video_id in video_ids:
        response = (
            analytics.reports()
            .query(
                ids="channel==MINE",
                startDate="2020-01-01",
                endDate=date.today().isoformat(),
                metrics="views",
                dimensions="insightTrafficSourceDetail",
                filters=f"video=={video_id};insightTrafficSourceType=={source_type}",
                maxResults=25,
                sort="-views",
            )
            .execute()
        )
        total += sum(row[1] for row in response.get("rows", []))
    return total


def fetch_view_duration_stats(analytics, video_ids: list[str]) -> tuple[int, float]:
    """주어진 영상들의 (총 조회수, 총 시청 시간(분)) 을 가져온다."""
    if not video_ids:
        return 0, 0.0
    response = (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate="2020-01-01",
            endDate=date.today().isoformat(),
            metrics="views,estimatedMinutesWatched",
            dimensions="video",
            filters=f"video=={','.join(video_ids)}",
            maxResults=25,
        )
        .execute()
    )
    total_views = 0
    total_minutes = 0.0
    for row in response.get("rows", []):
        _, views, minutes = row
        total_views += views
        total_minutes += minutes
    return total_views, total_minutes


def compute_average_view_duration_seconds(total_views: int, total_minutes: float) -> float:
    """조회수 가중 평균 시청 지속시간(초)을 계산한다."""
    return (total_minutes * 60 / total_views) if total_views else 0.0


def collect_engagement_metrics(analytics, video_ids: list[str], label: str) -> dict:
    """시청지속시간을 가져온다. (클릭율/노출수는 유튜브 Analytics API가 아예 제공하지 않아 제외)
    실패해도(HttpError) 전체 실행이 멈추지 않도록 한다."""
    result = {"avg_duration": None}

    try:
        views, minutes = fetch_view_duration_stats(analytics, video_ids)
        result["avg_duration"] = compute_average_view_duration_seconds(views, minutes)
    except HttpError as error:
        print(f"[{label}] 시청지속시간은 이번엔 못 가져왔어요: {error.reason}")

    return result


def collect_traffic_source(analytics, video_ids: list[str], source_type: str, label: str) -> int | None:
    """유입 경로별 조회수를 시도해서 가져오고, 실패하면 None을 반환한다."""
    try:
        return fetch_traffic_source_views(analytics, video_ids, source_type)
    except HttpError as error:
        print(f"[{label}] 유입 경로 데이터는 이번엔 못 가져왔어요: {error.reason}")
        return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("오류: YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    week = prompt_week_number()
    key_link = input("키콘텐츠 링크를 입력하세요: ").strip()
    key_video_id = extract_video_id(key_link)
    if not key_video_id:
        print("유효한 유튜브 링크가 아닙니다.")
        sys.exit(1)

    channel_text = prompt_channel_reference("채널 주소(@핸들 또는 channel/UC... URL)를 입력하세요")

    youtube = build("youtube", "v3", developerKey=api_key)
    channel_ref = parse_channel_reference(channel_text)
    uploads_playlist_id = get_uploads_playlist_id(youtube, channel_ref)
    all_video_ids = get_all_playlist_video_ids(youtube, uploads_playlist_id)
    pulling_video_ids = {video_id for video_id in all_video_ids if video_id != key_video_id}

    pulling_rows = fetch_video_stats(youtube, list(pulling_video_ids))
    pulling_total_views = sum(row["view_count"] for row in pulling_rows)

    print("구글 계정으로 로그인해서 연계 데이터를 가져올게요...")
    creds = get_oauth_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    source_views = fetch_related_video_traffic(analytics, key_video_id)
    linkage_views, linkage_rate = compute_linkage_rate(source_views, pulling_video_ids, pulling_total_views)

    pulling_video_id_list = list(pulling_video_ids)
    key_metrics = collect_engagement_metrics(analytics, [key_video_id], "키콘텐츠")
    pulling_metrics = collect_engagement_metrics(analytics, pulling_video_id_list, "풀링 콘텐츠")

    search_views = collect_traffic_source(analytics, [key_video_id], "YT_SEARCH", "키콘텐츠 검색 유입")
    page_views = collect_traffic_source(analytics, [key_video_id], "YT_OTHER_PAGE", "키콘텐츠 페이지 유입")
    # 유튜브 Analytics API에는 "탐색 기능" 전용 값이 따로 없어서, 가장 가까운 SUBSCRIBER
    # (홈 화면 + 구독 피드)로 근사한다. Shorts 스와이프 등 다른 발견 경로는 포함되지 않는다.
    browse_views = collect_traffic_source(analytics, pulling_video_id_list, "SUBSCRIBER", "풀링 콘텐츠 탐색 유입")

    workbook = get_or_create_workbook(REPORT_PATH)
    sheet = workbook[MAIN_SHEET_NAME]
    week_col = ensure_week_column(sheet, week)
    sheet.cell(row=LINKAGE_RATE_ROW, column=week_col, value=round(linkage_rate, 2))

    if key_metrics["avg_duration"] is not None:
        sheet.cell(row=KEY_AVG_VIEW_DURATION_ROW, column=week_col, value=round(key_metrics["avg_duration"], 1))
    if pulling_metrics["avg_duration"] is not None:
        sheet.cell(row=PULLING_AVG_VIEW_DURATION_ROW, column=week_col, value=round(pulling_metrics["avg_duration"], 1))
    if search_views is not None:
        sheet.cell(row=SEARCH_TRAFFIC_ROW, column=week_col, value=search_views)
    if page_views is not None:
        sheet.cell(row=PAGE_TRAFFIC_ROW, column=week_col, value=page_views)
    if browse_views is not None:
        sheet.cell(row=BROWSE_TRAFFIC_ROW, column=week_col, value=browse_views)

    workbook.save(REPORT_PATH)

    print(
        f"완료: {week}주차 - 키 콘텐츠 연계율 {linkage_rate:.2f}% "
        f"(연계 조회수 {linkage_views} / 풀링 콘텐츠 조회수 {pulling_total_views})"
    )
    print(f"       키콘텐츠 시청지속시간(초) {key_metrics['avg_duration']}")
    print(f"       풀링 콘텐츠 시청지속시간(초) {pulling_metrics['avg_duration']}")
    print(f"       검색 유입 {search_views}, 페이지 유입 {page_views}, 탐색 유입 {browse_views}")


if __name__ == "__main__":
    main()
