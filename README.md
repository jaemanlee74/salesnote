# SalesNote

영업기회를 탐색 단계부터 종료까지 기록하고 공유하는 사내 게시판입니다. 게시글 하나가 영업기회 하나이며, 단계 변경과 활동 기록이 그 아래 타임라인으로 쌓입니다.

요구사항은 [docs/SalesNote 기능명세서.md](docs/SalesNote%20기능명세서.md)에 있습니다.

## 구성

| 구분 | 내용 |
| --- | --- |
| 백엔드 | Python 3.12, FastAPI, SQLAlchemy 2 |
| DB | MySQL 8.4 |
| 화면 | 빌드 과정이 없는 단일 페이지(HTML, CSS, JS). 백엔드가 함께 제공 |
| 로그인 | 구글 계정(OAuth). 관리자가 허용한 계정만 접근 |
| 배포 | Docker Compose (web + db) |

```
backend/
  app/
    main.py          앱 조립, 보안 헤더, 세션
    config.py        환경 변수
    models.py        테이블 정의
    core.py          인증, 권한 규칙, 단계별 필수 입력
    services.py      타임라인, 알림(서비스 내·메일·구글 챗), 감사 기록
    jobs.py          하루 한 번 도는 작업(기한·정체 알림, 휴지통 정리)
    init_db.py       테이블 생성, 기본 코드, 최초 관리자
    routers/         auth, opps, records, misc, admin
    static/          화면
  tests/             주요 흐름 점검
docker-compose.yml
.env.example
```

## 실행

```bash
cp .env.example .env      # 비밀번호, SECRET_KEY, 구글 로그인 값, ADMIN_EMAILS 수정
docker compose up -d --build
```

`http://localhost:8000`으로 접속합니다. 처음 뜰 때 테이블과 기본 코드(단계, 사업 유형, 활동 유형, 실주 사유)를 만들고 `ADMIN_EMAILS`의 계정을 관리자로 등록합니다. 나머지 사용자는 관리자 화면의 허용 사용자에서 추가합니다.

### 구글 로그인 설정

1. Google Cloud 콘솔 → API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트 ID(웹 애플리케이션)를 만듭니다.
2. 승인된 리디렉션 URI에 `{BASE_URL}/auth/callback`을 넣습니다.
3. 클라이언트 ID와 보안 비밀을 `.env`의 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`에 넣습니다.

구글 로그인 없이 로컬에서 먼저 보려면 `.env`에 `DEV_LOGIN=true`를 둡니다. 허용 목록에 있는 메일만 입력해 로그인하는 개발용 기능이므로 운영에서는 반드시 끕니다.

### AWS 배포 시 확인할 것

- 로드밸런서(ALB)나 리버스 프록시에서 HTTPS를 종료하고 `web` 컨테이너의 8000번 포트로 넘깁니다.
- `.env`에서 `BASE_URL`을 실제 주소(https)로, `COOKIE_SECURE=true`, `DEV_LOGIN=false`로 둡니다.
- 데이터는 `db_data`(MySQL)와 `uploads`(첨부파일) 볼륨에 있습니다. 두 볼륨을 하루 1회 백업합니다. RDS를 쓰면 `db` 서비스를 빼고 `MYSQL_HOST` 등을 RDS로 맞춥니다.
- 테이블은 시작할 때 없는 것만 새로 만듭니다. 운영 중 컬럼을 바꿀 때는 별도 마이그레이션이 필요합니다.

## 기능 범위

기능명세서의 35개 기능을 다음과 같이 반영했습니다.

| 분류 | 반영 내용 |
| --- | --- |
| 영업기회 (OPP) | 제목·고객사만으로 등록, 상세, 수정(금액·일정·담당자 변경 이력), 휴지통 삭제와 30일 뒤 영구 삭제, 담당자·참여자, 공개 범위, 태그, 복제, 금액 열람 제한 |
| 단계 (STG) | 단계 변경과 사유, 단계별 필수 입력, 수주·실주·보류 종료 처리, 재개, 민간 바로 계약 |
| 진행 기록 (ACT) | 활동 기록(서식 텍스트), 타임라인과 유형별 보기, 다음 할 일, 첨부파일(50MB, 실행 파일 차단), 본인 기록 수정·삭제 |
| 소통 (CMT) | 댓글, @이름 멘션, 관심 등록 |
| 목록 (LST) | 게시판 목록, 칸반 보드(끌어서 단계 변경), 필터·정렬(주소에 반영), 통합 검색(일치 위치 표시), 엑셀 내보내기 |
| 알림 (NTF) | 서비스 내 알림, 메일 알림(SMTP 설정 시), 기한 하루 전·30일 정체 알림, 구글 챗 웹훅 |
| 대시보드 (DSH) | 단계별 건수·금액, 기한 임박 할 일, 최근 갱신, 수주·실주 통계 |
| 관리 (ADM) | 구글 로그인, 허용 사용자, 코드 관리, 구글 챗 연동, 휴지통, 감사 기록 |

### 권한

| 역할 | 할 수 있는 일 |
| --- | --- |
| 관리자 | 전체 열람·수정·삭제, 사용자·코드 관리 |
| 담당자 | 해당 기회의 정보 수정, 단계 변경, 담당자·참여자 지정, 본인 등록 건 삭제 |
| 참여자 | 진행 기록·할 일·첨부 작성 |
| 구성원 | 공개된 기회 열람, 댓글, 등록 |

예상 금액과 계약 금액은 관리자와 해당 기회의 담당자·참여자에게만 내려갑니다. 그 밖의 사용자에게는 목록, 상세, 변경 이력, 대시보드, 엑셀 모두에서 값을 보내지 않습니다. 비공개 기회는 권한이 없으면 목록과 검색에 나오지 않고 주소로 직접 열어도 404로 응답합니다.

## 개발

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest            # SQLite로 주요 흐름 점검

# 로컬 실행 (SQLite, 개발용 로그인)
export DATABASE_URL=sqlite:///./dev.db UPLOAD_DIR=./uploads DEV_LOGIN=true ADMIN_EMAILS=me@example.com
python -m app.init_db && uvicorn app.main:app --reload
```

`DEV_LOGIN=true`일 때 API 문서가 `/api/docs`에 열립니다.
