"""유튜브 영상 링크 목록을 받아 조회수/좋아요/댓글수 등을 수집하고 엑셀로 저장한다."""

import os
import re
import sys
from datetime import date

from dotenv import load_dotenv
from googleapiclient.discovery import build
from openpyxl import Workbook

VIDEO_ID_PATTERNS = [
    r"(?:v=|/videos/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
]


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


def save_to_excel(rows: list[dict], output_path: str) -> None:
    """수집한 통계를 엑셀 파일로 저장한다."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "유튜브 통계"
    headers = ["제목", "게시일", "조회수", "좋아요수", "댓글수", "영상 링크"]
    sheet.append(headers)
    for row in rows:
        sheet.append(
            [
                row["title"],
                row["published_at"],
                row["view_count"],
                row["like_count"],
                row["comment_count"],
                f"https://youtu.be/{row['video_id']}",
            ]
        )
    workbook.save(output_path)


def read_links_from_stdin() -> list[str]:
    print("유튜브 영상 링크를 한 줄에 하나씩 입력하세요. 입력이 끝나면 빈 줄에서 Enter를 누르세요.")
    links = []
    while True:
        line = input().strip()
        if not line:
            break
        links.append(line)
    return links


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("오류: YOUTUBE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    links = read_links_from_stdin()
    if not links:
        print("입력된 링크가 없습니다.")
        sys.exit(1)

    video_ids = []
    invalid_links = []
    for link in links:
        video_id = extract_video_id(link)
        if video_id:
            video_ids.append(video_id)
        else:
            invalid_links.append(link)

    if invalid_links:
        print("다음 링크에서는 영상 ID를 찾을 수 없어 제외했습니다:")
        for link in invalid_links:
            print(f"  - {link}")

    if not video_ids:
        print("유효한 유튜브 링크가 없습니다.")
        sys.exit(1)

    deduped_ids = dedupe_ids(video_ids)
    if len(deduped_ids) < len(video_ids):
        print(f"중복된 링크 {len(video_ids) - len(deduped_ids)}개는 한 번만 집계합니다.")
    video_ids = deduped_ids

    youtube = build("youtube", "v3", developerKey=api_key)
    rows = fetch_video_stats(youtube, video_ids)

    output_path = f"youtube_stats_{date.today().isoformat()}.xlsx"
    save_to_excel(rows, output_path)
    print(f"완료: {len(rows)}개 영상 통계를 {output_path} 파일에 저장했습니다.")


if __name__ == "__main__":
    main()
