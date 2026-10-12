"""Loop otak dengan LLM palsu (meniru tool-calling Claude) + triase."""
from core.brain import Brain


class ScriptedLLM:
    """LLM palsu: langkah 1 memanggil tool, langkah 2 menjawab dari hasil tool."""
    is_cloud = False
    has_any = False

    def __init__(self, calls):
        self.calls, self.seen_results = calls, []

    def describe(self):
        return "palsu"

    async def chat(self, system, messages, tools):
        last = messages[-1]
        if isinstance(last["content"], list):  # hasil tool
            self.seen_results.append(last["content"])
            return {"text": "Selesai.", "tool_calls": [], "content": [{"type": "text", "text": "Selesai."}]}
        blocks = [{"type": "tool_use", "id": f"t{i}", "name": n, "input": p} for i, (n, p) in enumerate(self.calls)]
        return {"text": "", "tool_calls": [{"id": b["id"], "name": b["name"], "input": b["input"]} for b in blocks], "content": blocks}

    async def complete(self, *a, **k):
        return ""


async def test_brain_tool_loop_and_approval_surface(ctx):
    ctx.llm = ScriptedLLM([("notes__add_note", {"text": "halo"}),
                           ("email__send_email", {"to": "a@b.co", "subject": "S", "body": "isi"})])
    out = await ctx.brain.handle("lakukan dua hal")
    assert out["text"] == "Selesai." and len(out["approvals"]) == 1
    assert out["tools"] == ["notes__add_note", "email__send_email"]
    assert ctx.db.kv_get("notes")[0]["text"] == "halo"


async def test_brain_history_trimmed_and_isolated(ctx):
    ctx.llm = ScriptedLLM([])
    for i in range(30):
        await ctx.brain.handle(f"pesan {i}", session="a")
    assert len(ctx.brain.history["a"]) <= 24 and "b" not in ctx.brain.history


async def test_brain_unknown_tool_is_reported_not_crashed(ctx):
    ctx.llm = ScriptedLLM([("ghost__do", {})])
    out = await ctx.brain.handle("x")
    assert out["text"] == "Selesai."


def test_heuristic_priority():
    h = Brain.heuristic_priority
    assert h("Tagihan jatuh tempo besok") == "high"
    assert h("Flash sale 50% diskon") == "low"
    assert h("Besok ketemu jam 5 ya") == "normal"
    assert h("halo", sender="Dosen Pembimbing", vips=["dosen"]) == "high"


async def test_proactive_notification_only_for_high(ctx):
    pushed = []

    async def n(text, aid):
        pushed.append(text)

    ctx.notifiers.append(n)
    await ctx.start()
    await ctx.bus.publish("wa", "notification", "vivo-s1", {"app": "com.whatsapp", "title": "Kampus", "text": "Deadline skripsi besok, segera kirim"})
    await ctx.bus.publish("shopee", "notification", "vivo-s1", {"app": "com.shopee.id", "title": "Promo", "text": "Flash sale diskon"})
    await ctx.bus.publish("wa", "notification", "vivo-s1", {"app": "com.whatsapp", "title": "Teman", "text": "lagi dimana?"})
    assert len(pushed) == 1 and "🔴" in pushed[0]


async def test_sensitive_notification_not_sent_to_llm(ctx):
    class Spy(ScriptedLLM):
        has_any = True
        called = False

        async def complete(self, *a, **k):
            Spy.called = True
            return ""

    ctx.llm = Spy([])
    res = await ctx.brain.triage({"type": "notification", "payload": {
        "app": "id.co.bankbri.brimo", "title": "BRImo", "text": "Kode OTP 123456", "sensitive": True}})
    assert not Spy.called and "disembunyikan" in res["summary"]


async def test_digest_and_status(ctx):
    await ctx.bus.publish("gmail", "email.received", "cloud", {"from": "a@b.co", "subject": "Tagihan", "snippet": ""})
    await ctx.bus.publish("wa", "notification", "vivo-s1", {"app": "com.whatsapp", "title": "A", "text": "b"})
    d = await ctx.registry.call("system", "digest", {})
    assert d["emails"] == 1 and d["notifications"] == 1 and "Tagihan" in d["text"]
    s = await ctx.registry.call("system", "status", {})
    assert "offline" in s["text"]
