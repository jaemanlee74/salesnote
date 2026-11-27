"""주요 흐름 점검. SQLite로 돈다:  cd backend && pytest"""
import os
import tempfile
from datetime import timedelta

_tmp = tempfile.mkdtemp(prefix="salesnote-test-")
os.environ.update(
    # 다른 DB로 돌리려면 TEST_DATABASE_URL을 지정한다 (예: mysql+pymysql://...)
    DATABASE_URL=os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"),
    UPLOAD_DIR=f"{_tmp}/uploads",
    DEV_LOGIN="true",
    ADMIN_EMAILS="admin@example.com",
    DISABLE_JOBS="1",
    SECRET_KEY="test",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.init_db import init  # noqa: E402
from app.jobs import run_daily  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Notification, Opportunity, Todo, today_kst, utcnow  # noqa: E402

H = {"X-SalesNote": "1"}


def client_for(email: str) -> TestClient:
    client = TestClient(app, headers=H)
    response = client.post("/auth/dev-login", json={"email": email})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture(scope="module")
def ctx():
    init()
    admin = client_for("admin@example.com")
    ids = {}
    for email, name in (("owner@example.com", "김담당"), ("part@example.com", "이참여"),
                        ("member@example.com", "박구성")):
        r = admin.post("/api/admin/users", json={"email": email, "name": name})
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    return {
        "admin": admin, "ids": ids,
        "owner": client_for("owner@example.com"),
        "part": client_for("part@example.com"),
        "member": client_for("member@example.com"),
    }


def test_login_is_restricted(ctx):
    anonymous = TestClient(app, headers=H)
    assert anonymous.get("/api/me").status_code == 401
    assert anonymous.get("/api/opportunities").status_code == 401
    assert anonymous.post("/auth/dev-login", json={"email": "x@example.com"}).status_code == 403
    # 화면이 붙이는 헤더가 없으면 상태 변경 요청을 받지 않는다
    assert TestClient(app).post("/auth/dev-login", json={"email": "admin@example.com"}).status_code == 403
    assert ctx["member"].get("/api/admin/users").status_code == 403


def test_opportunity_flow(ctx):
    owner, part, member, admin, ids = (ctx[k] for k in ("owner", "part", "member", "admin", "ids"))

    assert owner.post("/api/opportunities", json={"title": "제목만"}).status_code == 422
    r = owner.post("/api/opportunities", json={
        "title": "AI 포털 구축", "customer": "한국대학교", "biz_type": "private",
        "participant_ids": [ids["이참여"]], "tags": ["AI", "공공"],
        "overview": "<p>배경 <script>alert(1)</script><b>굵게</b></p>",
    })
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    ctx["oid"] = oid

    data = owner.get(f"/api/opportunities/{oid}").json()
    assert data["opp"]["stage"] == "explore"
    assert "script" not in data["opp"]["overview"] and "<b>굵게</b>" in data["opp"]["overview"]
    assert data["timeline"][0]["event"] == "created"
    assert [s["title"] for s in owner.get("/api/opportunities/similar?customer=한국대학교").json()]

    # 구성원은 수정·단계 변경·기록 작성을 할 수 없다
    assert member.patch(f"/api/opportunities/{oid}", json={"title": "x"}).status_code == 403
    assert member.post(f"/api/opportunities/{oid}/stage", json={"stage": "contact"}).status_code == 403
    assert member.post(f"/api/opportunities/{oid}/activities",
                       json={"type": "memo", "content": "x"}).status_code == 403
    assert part.patch(f"/api/opportunities/{oid}", json={"title": "x"}).status_code == 403

    # 단계 진입 필수 입력
    r = owner.post(f"/api/opportunities/{oid}/stage", json={"stage": "prepare"})
    assert r.status_code == 422 and set(r.json()["detail"]["missing"]) == {"amount_expected", "expected_period"}
    r = owner.post(f"/api/opportunities/{oid}/stage", json={
        "stage": "prepare", "reason": "참여 결정",
        "fields": {"amount_expected": 500000000, "expected_period": "2027-03"}})
    assert r.status_code == 200, r.text

    # 금액 열람 제한: 담당자·참여자·관리자만
    for client, visible in ((owner, True), (part, True), (admin, True), (member, False)):
        opp = client.get(f"/api/opportunities/{oid}").json()["opp"]
        assert (opp["amount_expected"] == 500000000) is visible
        item = next(i for i in client.get("/api/opportunities").json()["items"] if i["id"] == oid)
        assert (item["amount_expected"] is not None) is visible
    owner.patch(f"/api/opportunities/{oid}", json={"amount_expected": 600000000})
    change = next(t for t in member.get(f"/api/opportunities/{oid}").json()["timeline"]
                  if t["event"] == "field_change")
    assert change["meta"]["masked"] and change["meta"]["after"] is None
    assert member.get("/api/dashboard").json()["stages"]["prepare"] == {"count": 1, "amount": 0, "hidden": 1}
    assert owner.get("/api/dashboard").json()["stages"]["prepare"]["amount"] == 600000000


def test_records(ctx):
    owner, part, member, oid = ctx["owner"], ctx["part"], ctx["member"], ctx["oid"]

    r = part.post(f"/api/opportunities/{oid}/activities", json={
        "type": "meeting", "content": "<p>고객 미팅 진행, 예산 확인. @김담당 확인 부탁</p>"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert owner.patch(f"/api/activities/{aid}", json={"type": "memo", "content": "x"}).status_code == 403
    assert part.patch(f"/api/activities/{aid}", json={"type": "meeting", "content": "<p>예산 확인 완료</p>"}).status_code == 200

    # 구성원도 댓글은 달 수 있다
    r = member.post(f"/api/opportunities/{oid}/comments", json={"content": "@이참여 자료 공유 부탁드립니다", "activity_id": aid})
    assert r.status_code == 201, r.text
    kinds = {n["kind"] for n in part.get("/api/notifications").json()}
    assert "mention" in kinds
    assert {"mention", "stage"} <= {n["kind"] for n in owner.get("/api/notifications").json()} | {"stage"}
    assert owner.get("/api/notifications/count").json()["unread"] > 0
    owner.post("/api/notifications/read-all")
    assert owner.get("/api/notifications/count").json()["unread"] == 0

    r = owner.post(f"/api/opportunities/{oid}/todos", json={
        "content": "제안서 초안", "due_date": str(today_kst() + timedelta(days=1))})
    tid = r.json()["id"]
    item = next(i for i in owner.get("/api/opportunities").json()["items"] if i["id"] == oid)
    assert item["next_todo"]["content"] == "제안서 초안" and item["comment_count"] == 1

    with SessionLocal() as db:
        assert run_daily(db)["due"] == 1
    assert any(n["kind"] == "due" for n in owner.get("/api/notifications").json())
    assert owner.patch(f"/api/todos/{tid}", json={"done": True}).json()["done"] is True

    # 첨부파일
    r = owner.post(f"/api/opportunities/{oid}/attachments", files={"file": ("RFP 문서.pdf", b"pdf-bytes")}, data={"activity_id": str(aid)})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert member.get(f"/api/attachments/{fid}").content == b"pdf-bytes"
    assert owner.post(f"/api/opportunities/{oid}/attachments", files={"file": ("run.exe", b"x")}).status_code == 422
    assert member.post(f"/api/opportunities/{oid}/attachments", files={"file": ("a.txt", b"x")}).status_code == 403

    data = owner.get(f"/api/opportunities/{oid}").json()
    activity = next(t for t in data["timeline"] if t["id"] == aid)
    assert activity["edited"] and len(activity["comments"]) == 1 and len(activity["attachments"]) == 1
    assert any(t["event"] == "todo_done" for t in data["timeline"])

    # 검색: 기록 본문에서 일치
    found = owner.get("/api/opportunities", params={"q": "예산 확인"}).json()["items"]
    assert found and "기록" in found[0]["match"]
    assert owner.get("/api/opportunities", params={"q": "없는검색어"}).json()["total"] == 0
    assert owner.get("/api/opportunities", params={"tag": "AI", "quick": "mine"}).json()["total"] == 1
    assert member.get("/api/opportunities", params={"quick": "mine"}).json()["total"] == 0

    r = owner.get("/api/opportunities/export")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_private_and_close(ctx):
    owner, member, admin, oid = ctx["owner"], ctx["member"], ctx["admin"], ctx["oid"]

    owner.patch(f"/api/opportunities/{oid}", json={"visibility": "private"})
    assert member.get(f"/api/opportunities/{oid}").status_code == 404
    assert member.get("/api/opportunities").json()["total"] == 0
    assert member.get("/api/opportunities", params={"q": "AI"}).json()["total"] == 0
    assert member.get("/api/customers").json() == []
    owner.patch(f"/api/opportunities/{oid}", json={"visibility": "public"})

    member.post(f"/api/opportunities/{oid}/watch")
    # 바로 계약(민간)
    r = owner.post(f"/api/opportunities/{oid}/stage", json={"stage": "won", "direct": True})
    assert r.status_code == 422
    r = owner.post(f"/api/opportunities/{oid}/stage", json={
        "stage": "won", "direct": True,
        "fields": {"contract_amount": 550000000, "contract_date": str(today_kst())}})
    assert r.status_code == 200, r.text
    assert any(n["kind"] == "stage" for n in member.get("/api/notifications").json())
    assert owner.get("/api/opportunities").json()["total"] == 0  # 종료 건은 기본 보기에서 제외
    assert owner.get("/api/opportunities", params={"quick": "closed"}).json()["total"] == 1
    assert owner.get("/api/dashboard").json()["stats"]["win_rate"] == 100

    # 재개 후 실주 처리에는 사유가 필요하다
    assert owner.post(f"/api/opportunities/{oid}/stage", json={"stage": "negotiate"}).status_code == 200
    assert owner.post(f"/api/opportunities/{oid}/stage", json={"stage": "lost"}).status_code == 422
    assert owner.post(f"/api/opportunities/{oid}/stage", json={
        "stage": "lost", "fields": {"close_reason_code": "price"}}).status_code == 200

    # 휴지통: 삭제 → 복구 → 삭제 → 30일 뒤 영구 삭제
    assert member.delete(f"/api/opportunities/{oid}").status_code == 403
    assert owner.delete(f"/api/opportunities/{oid}").status_code == 200
    assert owner.get(f"/api/opportunities/{oid}").status_code == 404
    assert [t["id"] for t in admin.get("/api/admin/trash").json()] == [oid]
    assert admin.post(f"/api/admin/trash/{oid}/restore").status_code == 200
    assert owner.get(f"/api/opportunities/{oid}").status_code == 200
    owner.delete(f"/api/opportunities/{oid}")
    with SessionLocal() as db:
        db.get(Opportunity, oid).deleted_at = utcnow() - timedelta(days=31)
        db.commit()
        assert run_daily(db)["purged"] == 1
        assert db.get(Opportunity, oid) is None
        assert db.query(Todo).count() == 0 and db.query(Notification).filter_by(opportunity_id=oid).count() == 0
    actions = {row["action"] for row in admin.get("/api/admin/audit").json()["items"]}
    assert {"login", "delete", "export", "view_restricted"} <= actions


def test_admin(ctx):
    admin, ids = ctx["admin"], ctx["ids"]
    codes = admin.get("/api/admin/codes").json()
    stage = next(c for c in codes if c["code"] == "explore")
    assert admin.patch(f"/api/admin/codes/{stage['id']}", json={"name": "발굴"}).json()["name"] == "발굴"
    assert admin.patch(f"/api/admin/codes/{stage['id']}", json={"is_active": False}).status_code == 422
    assert admin.post("/api/admin/codes", json={"kind": "loss_reason", "name": "일정"}).status_code == 201
    assert admin.put("/api/admin/chat", json={"webhook": "http://evil.example/x"}).status_code == 422

    # 사용 중지한 계정은 즉시 차단된다
    assert admin.patch(f"/api/admin/users/{ids['박구성']}", json={"is_active": False}).status_code == 200
    assert ctx["member"].get("/api/me").status_code == 401
    me = admin.get("/api/me").json()
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"role": "member"}).status_code == 422
