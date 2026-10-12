"""Registry, antrean persetujuan, event bus, dan kemampuan menambah plugin baru."""
import textwrap

from core.context import Context
from tests.conftest import make_settings


async def test_skills_discovered(ctx):
    assert {"email", "notif", "instagram", "system", "notes"} <= set(ctx.registry.skills)
    assert not ctx.registry.errors


async def test_tool_specs_valid_names(ctx):
    import re
    specs = ctx.registry.tool_specs()
    assert specs
    for s in specs:
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", s["name"]) and "__" in s["name"]
        assert s["input_schema"]["type"] == "object"


async def test_write_action_requires_approval_and_executes_on_approve(ctx):
    sent = []

    async def fake_run(action, params):
        sent.append((action, params))
        return {"status": "sent", "text": "terkirim"}

    ctx.registry.get("email").run = fake_run
    pushed = []

    async def notifier(text, aid):
        pushed.append((text, aid))

    ctx.notifiers.append(notifier)
    res = await ctx.registry.call("email", "send_email", {"to": "a@b.co", "subject": "Hi", "body": "isi"})
    assert res["status"] == "pending_approval" and not sent          # BELUM terkirim
    assert pushed and pushed[0][1] == res["approval_id"]              # pemilik diberi tahu
    out = await ctx.approvals.approve(res["approval_id"], edits={"body": "isi diedit"})
    assert out["status"] == "executed"
    assert sent == [("send_email", {"to": "a@b.co", "subject": "Hi", "body": "isi diedit"})]
    again = await ctx.approvals.approve(res["approval_id"])
    assert "error" in again and len(sent) == 1                        # tidak bisa dieksekusi dua kali


async def test_reject_and_edit(ctx):
    res = await ctx.registry.call("email", "send_email", {"to": "a@b.co", "subject": "S", "body": "lama"})
    ed = await ctx.approvals.edit(res["approval_id"], "baru")
    assert ed["status"] == "pending"
    assert ctx.db.get_approval(res["approval_id"])["params"]["body"] == "baru"
    rej = await ctx.approvals.reject(res["approval_id"])
    assert rej["status"] == "rejected"
    assert "error" in await ctx.approvals.approve(res["approval_id"])


async def test_approval_expires(ctx):
    res = await ctx.registry.call("email", "send_email", {"to": "a@b.co", "subject": "S", "body": "x"})
    ctx.db.conn.execute("UPDATE approvals SET ts=ts-999999")
    out = await ctx.approvals.approve(res["approval_id"])
    assert "kedaluwarsa" in out["error"]


async def test_missing_required_param(ctx):
    assert "error" in await ctx.registry.call("notes", "add_note", {})
    assert "error" in await ctx.registry.call("nope", "x", {})


async def test_bus_handler_isolation(ctx):
    got = []
    ctx.bus.subscribe(lambda e: 1 / 0)          # handler rusak
    ctx.bus.subscribe(lambda e: got.append(e))  # tetap harus terpanggil
    ev = await ctx.bus.publish("t", "x.y", "dev", {"a": 1})
    assert got and ev["id"]
    assert ctx.db.recent_events(type_="x.y")[0]["payload"] == {"a": 1}


async def test_add_new_skill_by_dropping_one_file(tmp_path):
    """Bukti 'tambah fitur = tambah satu file': plugin di folder eksternal otomatis termuat."""
    ext = tmp_path / "plugins"
    ext.mkdir()
    (ext / "hello_skill.py").write_text(textwrap.dedent('''
        from skills.base import Action, Skill
        class HelloSkill(Skill):
            name = "hello"
            description = "Menyapa"
            ACTIONS = [Action("greet", "Sapa seseorang", {"who": {"type": "string"}}, ["who"])]
            async def do_greet(self, who):
                return {"text": f"Halo, {who}!"}
    '''))
    c = Context(make_settings(tmp_path, skills={"extra_dirs": [str(ext)]}))
    assert "hello" in c.registry.skills
    assert any(t["name"] == "hello__greet" for t in c.registry.tool_specs())
    assert (await c.registry.call("hello", "greet", {"who": "Tony"}))["text"] == "Halo, Tony!"


async def test_broken_plugin_does_not_break_system(tmp_path):
    ext = tmp_path / "plugins"
    ext.mkdir()
    (ext / "bad_skill.py").write_text("raise RuntimeError('oops')")
    c = Context(make_settings(tmp_path, skills={"extra_dirs": [str(ext)]}))
    assert "bad_skill" in c.registry.errors and "notes" in c.registry.skills


async def test_disabled_skill(tmp_path):
    c = Context(make_settings(tmp_path, skills={"disabled": ["instagram"]}))
    assert "instagram" not in c.registry.skills
