"""Antarmuka Telegram — jalan di semua HP Android dan iPad tanpa membuat app.

Hanya TELEGRAM_OWNER_ID yang dilayani; pengirim lain diabaikan dan dicatat di audit.
Kartu persetujuan punya tombol ✅ Kirim / ✏️ Edit / ❌ Batal.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from core.util import chunk

log = logging.getLogger("jarvis.telegram")


class TelegramInterface:
    def __init__(self, ctx: Any, token: str, owner_id: int):
        self.ctx, self.owner_id = ctx, owner_id
        self.app = Application.builder().token(token).build()
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("inbox", self.cmd_inbox))
        self.app.add_handler(CommandHandler("pending", self.cmd_pending))
        self.app.add_handler(CallbackQueryHandler(self.on_button, pattern=r"^ap:"))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

    # ---- siklus hidup -----------------------------------------------------
    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        self.ctx.notifiers.append(self.push)
        log.info("Bot Telegram aktif")

    async def stop(self) -> None:
        if self.push in self.ctx.notifiers:
            self.ctx.notifiers.remove(self.push)
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # ---- util -------------------------------------------------------------
    def _owner(self, update: Update) -> bool:
        uid = update.effective_user.id if update.effective_user else None
        if uid != self.owner_id:
            self.ctx.db.audit("unknown", "telegram.unauthorized", {"user_id": uid})
            return False
        return True

    @staticmethod
    def _keyboard(aid: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Kirim", callback_data=f"ap:a:{aid}"),
            InlineKeyboardButton("✏️ Edit", callback_data=f"ap:e:{aid}"),
            InlineKeyboardButton("❌ Batal", callback_data=f"ap:r:{aid}"),
        ]])

    async def push(self, text: str, approval_id: str | None = None) -> None:
        """Notifier proaktif dari Context.notify()."""
        parts = chunk(text)
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            await self.app.bot.send_message(
                self.owner_id, part, reply_markup=self._keyboard(approval_id) if (approval_id and last) else None)

    async def _reply(self, update: Update, text: str) -> None:
        for part in chunk(text or "(kosong)"):
            await update.effective_message.reply_text(part)

    # ---- perintah ----------------------------------------------------------
    async def cmd_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._owner(update):
            await self._reply(update, "Jarvis siap. Coba: \"cek email\", \"notifikasi terbaru\", \"dm instagram\", \"ringkasan hari ini\".\n"
                                      "/status /inbox /pending")

    async def _run(self, update: Update, skill: str, action: str) -> None:
        if self._owner(update):
            res = await self.ctx.registry.call(skill, action, {}, actor="owner")
            await self._reply(update, res.get("text") or res.get("error", ""))

    async def cmd_status(self, update, _):  await self._run(update, "system", "status")
    async def cmd_inbox(self, update, _):   await self._run(update, "notif", "recent")

    async def cmd_pending(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._owner(update):
            return
        rows = self.ctx.approvals.pending()
        if not rows:
            await self._reply(update, "Tidak ada persetujuan tertunda.")
        for r in rows:
            body = self.ctx.approvals.preview(r["params"])
            await update.effective_message.reply_text(
                f"✋ [{r['id']}] {r['summary']}" + (f"\n\n{body}" if body else ""), reply_markup=self._keyboard(r["id"]))

    # ---- pesan & tombol -----------------------------------------------------
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._owner(update):
            return
        editing = context.chat_data.pop("editing", None)
        if editing:
            res = await self.ctx.approvals.edit(editing, update.effective_message.text)
            if "error" in res:
                await self._reply(update, res["error"])
            return
        await update.effective_chat.send_action("typing")
        out = await self.ctx.brain.handle(update.effective_message.text, session=f"tg:{self.owner_id}")
        await self._reply(update, out["text"])

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not self._owner(update):
            await q.answer("Tidak diizinkan", show_alert=True)
            return
        _, op, aid = q.data.split(":", 2)
        await q.answer()
        if op == "a":
            res = await self.ctx.approvals.approve(aid)
            msg = ("✅ " if "error" not in res else "⚠️ ") + (res.get("text") or res.get("error", ""))
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text(msg)
        elif op == "r":
            res = await self.ctx.approvals.reject(aid)
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_text(res.get("text") or res.get("error", ""))
        elif op == "e":
            context.chat_data["editing"] = aid
            await q.message.reply_text(f"Kirim teks baru untuk draf [{aid}] (pesan berikutnya akan menggantikan drafnya).")
