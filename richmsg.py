"""Rich Messages (buttons inside the message bubble) with automatic fallback.

Buttons are described once as Btn objects. richmsg.send / richmsg.edit render them as
  1) a Telegram Rich Message (sendRichMessage / editMessageText + rich_message), and
  2) if Telegram refuses that for any reason, a normal message with normal inline buttons.
Set RICH_BUTTONS=0 in the environment to switch the rich look off completely.
"""
import html
import logging

import aiohttp
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from compat import NOPREVIEW, reply_kw
from config import Config

log = logging.getLogger("richmsg")
API = f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
_session = None


class Btn:
    """style: None | 'primary' (blue) | 'success' (green) | 'danger' (red)"""

    def __init__(self, text: str, cb: str = None, url: str = None, style: str = None):
        self.text, self.cb, self.url, self.style = text, cb, url, style


# ---------- rendering ----------
def body_html(text: str) -> str:
    """texts.py messages are HTML with newlines; rich HTML needs one <p> per line."""
    return "".join(f"<p>{line}</p>" for line in text.split("\n") if line.strip())


def _btn_html(b: Btn) -> str:
    st = f' style="{b.style}"' if b.style else ""
    label = html.escape(b.text)
    if b.url:
        return f'<tg-button type="url"{st} url="{html.escape(b.url, quote=True)}">{label}</tg-button>'
    return f'<tg-button type="callback_data"{st} data="{html.escape(b.cb or "noop", quote=True)}">{label}</tg-button>'


def rows_html(rows: list) -> str:
    return "".join("<tg-button-row>" + "".join(_btn_html(b) for b in r) + "</tg-button-row>" for r in rows if r)


def markup(rows: list):
    """The same buttons as a normal inline keyboard (fallback path)."""
    out = []
    for r in rows or []:
        line = [
            InlineKeyboardButton(b.text, url=b.url) if b.url else InlineKeyboardButton(b.text, callback_data=b.cb or "noop")
            for b in r
        ]
        if line:
            out.append(line)
    return InlineKeyboardMarkup(out) if out else None


# ---------- raw Bot API ----------
async def _api(method: str, payload: dict) -> dict:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try:
        async with _session.post(f"{API}/{method}", json=payload) as r:
            return await r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def send(client, chat_id: int, text: str, rows: list, reply_to: int = None) -> int:
    """Send text + buttons. Returns the new message id."""
    if Config.RICH_BUTTONS and rows:
        payload = {"chat_id": chat_id, "rich_message": {"html": body_html(text) + rows_html(rows)}}
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        res = await _api("sendRichMessage", payload)
        if res.get("ok"):
            return res["result"]["message_id"]
        log.warning("sendRichMessage failed, using normal buttons: %s", res.get("description"))
    sent = await client.send_message(
        chat_id, text, reply_markup=markup(rows), **NOPREVIEW, **reply_kw(reply_to)
    )
    return sent.id


async def edit(msg, text: str, rows: list):
    """Edit a bot message (e.g. Next / Back). msg = callback_query.message"""
    if Config.RICH_BUTTONS:
        res = await _api("editMessageText", {
            "chat_id": msg.chat.id,
            "message_id": msg.id,
            "rich_message": {"html": body_html(text) + rows_html(rows)},
        })
        if res.get("ok"):
            return
        desc = str(res.get("description", ""))
        if "not modified" in desc.lower():
            return
        log.warning("rich edit failed, using normal edit: %s", desc)
    try:
        await msg.edit_text(text, reply_markup=markup(rows), **NOPREVIEW)
    except MessageNotModified:
        pass
    except Exception:
        log.exception("edit failed")
