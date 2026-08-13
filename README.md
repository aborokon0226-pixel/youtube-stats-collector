# 유튜브 영상 통계 수집기

유튜브 영상 링크 여러 개를 입력하면, 조회수·좋아요수·댓글수·게시일을 자동으로 가져와서 엑셀 파일로 저장해주는 프로그램입니다.

## 1. 준비하기

이 프로그램을 실행하려면 Python이 설치되어 있어야 합니다.

필요한 패키지를 설치하세요:

```bash
pip install -r requirements.txt
```

## 2. 유튜브 API 키 설정하기

1. `.env.example` 파일을 복사해서 `.env`라는 이름으로 저장하세요.
2. `.env` 파일을 열어서 아래처럼 본인의 유튜브(구글) API 키를 입력하세요.

```
YOUTUBE_API_KEY=발급받은_API_키
```

`.env` 파일은 절대 GitHub에 올리지 마세요 (`.gitignore`에 이미 등록되어 있어 자동으로 제외됩니다).

## 3. 실행하기

```bash
python youtube_stats.py
```

실행하면 유튜브 영상 링크를 한 줄에 하나씩 입력하라는 안내가 나옵니다. 링크를 다 입력했으면 빈 줄에서 Enter를 눌러 종료하세요.

예시:
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://youtu.be/dQw4w9WgXcQ
(빈 줄에서 Enter)
```

실행이 끝나면 `youtube_stats_YYYY-MM-DD.xlsx` 파일이 생성되며, 여기에 영상별 통계가 저장됩니다.

## 4. 테스트 실행하기

```bash
python -m unittest
```

## 참고

- 이 프로그램은 유튜브에 공개된 데이터(조회수, 좋아요수, 댓글수, 게시일)만 가져옵니다.
- 시청지속시간, 유입경로, 구독전환율처럼 채널 소유자만 볼 수 있는 데이터는 이번 버전에는 포함되어 있지 않습니다.
