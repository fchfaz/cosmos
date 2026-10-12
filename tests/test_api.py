"""API end-to-end (TestClient): perangkat -> ingest -> inbox, auth, chat offline, persetujuan."""
import httpx
from fastapi.testclient import TestClient

OWNER = {"X-API-Key": "testkey"}


def register(client, name="vivo-s1"):
    r = client.post("/devices", json={"name": name, "platform": "android"}, headers=OWNER)
    assert r.status_code == 200
    return r.json()["token"]


def test_health_open_but_owner_endpoints_need_key(app):
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/devices").status_code == 401
        assert c.get("/devices", headers={"X-API-Key": "salah"}).status_code == 401
        assert c.get("/devices", headers=OWNER).status_code == 200


def test_ingest_requires_valid_device_token(app):
    with TestClient(app) as c:
        body = {"app": "com.whatsapp", "title": "Annisa", "text": "Halo"}
        assert c.post("/ingest/notification", json=body).status_code == 401
        assert c.post("/ingest/notification", json=body, headers={"X-Device-Token": "palsu"}).status_code == 401
        tok = register(c)
        r = c.post("/ingest/notification", json=body, headers={"X-Device-Token": tok})
        assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_notification_flow_dedup_ignore_sensitive_and_device_from_token(app):
    with TestClient(app) as c:
        t1, t2 = register(c, "vivo-s1"), register(c, "oppo-a77s")
        n = {"app": "com.whatsapp", "title": "Annisa", "text": "Sudah makan?",
             "device": "PALSU"}  # nama perangkat di body harus diabaikan
        assert c.post("/ingest/notification", json=n, headers={"X-Device-Token": t1}).json()["status"] == "accepted"
        # notifikasi sama muncul di HP kedua (akun sama) -> duplikat
        assert c.post("/ingest/notification", json=n, headers={"X-Device-Token": t2}).json()["reason"] == "duplikat"
        assert c.post("/ingest/notification", json={"app": "com.android.systemui", "title": "x", "text": "y"},
                      headers={"X-Device-Token": t1}).json()["status"] == "ignored"
        assert c.post("/ingest/notification", json={"app": "com.whatsapp", "title": "", "text": ""},
                      headers={"X-Device-Token": t1}).json()["status"] == "ignored"
        otp = c.post("/ingest/notification", json={"app": "id.co.bankbri.brimo", "title": "BRImo", "text": "Kode OTP 551827"},
                     headers={"X-Device-Token": t1}).json()
        assert otp["sensitive"] is True
        ev = c.get("/events?type=notification", headers=OWNER).json()
        assert {e["device"] for e in ev} == {"vivo-s1"}              # dari token, bukan body
        chat = c.post("/chat", json={"text": "notifikasi terbaru"}, headers=OWNER).json()
        assert "Sudah makan?" in chat["text"] and "WhatsApp" in chat["text"]


def test_unknown_kind_and_bad_payload(app):
    with TestClient(app) as c:
        tok = register(c)
        h = {"X-Device-Token": tok}
        assert c.post("/ingest/lokasi", json={}, headers=h).status_code == 404
        assert c.post("/ingest/notification", content=b"bukan json", headers=h).status_code == 400
        assert c.post("/ingest/notification", content=b"x" * 70000, headers=h).status_code == 413


def test_revoked_device_loses_access(app):
    with TestClient(app) as c:
        tok = register(c, "redmi-4x")
        assert c.delete("/devices/redmi-4x", headers=OWNER).json()["removed"]
        r = c.post("/ingest/notification", json={"app": "a", "title": "t", "text": "x"}, headers={"X-Device-Token": tok})
        assert r.status_code == 401


def test_chat_offline_commands_and_help(app):
    with TestClient(app) as c:
        r = c.post("/chat", json={"text": "catat beli kabel HDMI"}, headers=OWNER).json()
        assert "Tercatat" in r["text"]
        r = c.post("/chat", json={"text": "catatan"}, headers=OWNER).json()
        assert "kabel HDMI" in r["text"]
        r = c.post("/chat", json={"text": "status"}, headers=OWNER).json()
        assert "Skill:" in r["text"]
        r = c.post("/chat", json={"text": "balas email pak budi"}, headers=OWNER).json()
        assert "ANTHROPIC_API_KEY" in r["text"]


def test_approval_endpoints_and_pwa_outbox(app):
    ctx = app.state.ctx
    with TestClient(app) as c:
        r = c.portal.call(ctx.registry.call, "email", "send_email", {"to": "a@b.co", "subject": "S", "body": "isi"})
        assert r["status"] == "pending_approval"
        pend = c.get("/approvals", headers=OWNER).json()
        assert len(pend) == 1 and pend[0]["id"] == r["approval_id"]
        out = c.get("/outbox?after=0", headers=OWNER).json()
        assert out and out[0]["approval_id"] == r["approval_id"]
        rej = c.post(f"/approvals/{r['approval_id']}/reject", headers=OWNER).json()
        assert rej["status"] == "rejected"
        assert c.get("/approvals", headers=OWNER).json() == []


def test_pwa_files_served(app):
    with TestClient(app) as c:
        assert "JARVIS" in c.get("/").text
        assert c.get("/manifest.webmanifest").status_code == 200
        assert c.get("/sw.js").status_code == 200


def test_instagram_via_notifications_and_draft_only(app):
    with TestClient(app) as c:
        tok = register(c)
        c.post("/ingest/notification", headers={"X-Device-Token": tok},
               json={"app": "com.instagram.android", "title": "dina.store", "text": "Kak, ready stock?"})
        r = c.post("/chat", json={"text": "dm instagram"}, headers=OWNER).json()
        assert "dina.store" in r["text"] and "ready stock" in r["text"]
        ctx = app.state.ctx
        d = c.portal.call(ctx.registry.call, "instagram", "draft_reply", {"who": "dina.store", "instruction": "ready kak"})
        assert d["status"] == "draft_only" and "manual" in d["text"]


async def test_instagram_graph_api_send_goes_through_approval(ctx, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("IG_USER_ID", "17841")
    ctx.settings.data["instagram"]["mode"] = "graph_api"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["json"] = str(request.url), request.headers.get("authorization"), request.content
        return httpx.Response(200, json={"message_id": "m"})

    ig = ctx.registry.get("instagram")
    ig.transport = httpx.MockTransport(handler)
    d = await ctx.registry.call("instagram", "draft_reply", {"who": "dina", "instruction": "ready kak", "recipient_id": "999"})
    assert d["status"] == "pending_approval" and not seen              # belum dikirim
    out = await ctx.approvals.approve(d["approval_id"])
    assert out["status"] == "executed"
    assert seen["auth"] == "Bearer tok" and "access_token" not in seen["url"] and b"999" in seen["json"]


async def test_instagram_send_blocked_in_notification_mode(ctx):
    res = await ctx.registry.get("instagram").run("send_dm", {"recipient_id": "1", "text": "x"})
    assert "graph_api" in res["error"]
