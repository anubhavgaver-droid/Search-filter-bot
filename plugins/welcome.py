"""
Group welcome / goodbye (drop-in plugin: put this file in your plugins/ folder and redeploy - nothing else to change).

WHEN   a member joins  -> welcome message   |   a member leaves -> goodbye message
       both are removed automatically after AUTO_DELETE seconds (5 minutes by default)
WHO    bot owners (ADMINS) and the group's own admins can configure it, inside the group

COMMANDS (inside the group)
  /welcome            status + help          /welcome on|off      /goodbye on|off
  /setwelcome <text>  set the text. Or REPLY to a text / photo / GIF / video with /setwelcome
                      (or send a photo with the caption "/setwelcome your text")
  /setwelcome reset   back to default        /delwelcomephoto     remove the photo only
  /setgoodbye <text>  /setgoodbye reset
  /addbutton Text | https://link [| same]    add a button ("same" = put it in the previous row)
  /delbutton 2        /buttons               /clearbuttons
  /testwelcome        preview it with yourself as the new member

PLACEHOLDERS  {mention} (tags them) {first} {last} {fullname} {username} {id} {group} {count}
Text supports Telegram formatting (bold, italic, links, emoji, premium emoji). Settings live in MongoDB via
database.get_meta / set_meta.
"""
import html
import re
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database as db
from config import Config

AUTO_DELETE = getattr(Config, "AUTO_DELETE", 300)
MAX_BUTTONS, MAX_ROWS, MAX_PER_ROW = 8, 6, 3

DEFAULT_WELCOME = (
    "👋 <b>Welcome {mention}!</b>\n\n"
    "Glad to have you in <b>{group}</b> 🎉\n"
    "• Type any story name here to search it\n"
    "• /filters - all stories · /request <i>name</i> - ask for a story"
)
DEFAULT_GOODBYE = "👋 <b>{fullname}</b> left <b>{group}</b>. Take care, come back anytime! 💙"

_last = {}   # (kind, chat id) -> last time, so a join raid doesn't flood the group
_cache = {}  # chat id -> settings dict


# ---------------- helpers ----------------
def _esc(s) -> str:
    return html.escape(str(s or ""))


def _mention(u) -> str:
    return f'<a href="tg://user?id={u.id}">{_esc((u.first_name or "User")[:30])}</a>'


def _vars(u, chat, count) -> dict:
    first, last = u.first_name or "", getattr(u, "last_name", None) or ""
    full = (first + " " + last).strip() or "User"
    username = getattr(u, "username", None)
    return {
        "{mention}": _mention(u), "{name}": _mention(u),
        "{first}": _esc(first or "User"), "{last}": _esc(last), "{fullname}": _esc(full),
        "{username}": f"@{username}" if username else _esc(first or "User"),
        "{id}": str(u.id), "{group}": _esc(chat.title or "this group"), "{count}": str(count),
    }


def _render(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace(k, v)
    return template


def _clean_url(u: str):
    u = u.strip()
    if u.startswith("@") and len(u) > 2:
        u = "https://t.me/" + u[1:]
    elif re.match(r"^(t\.me|telegram\.me)/", u):
        u = "https://" + u
    return u if re.match(r"^(https?://|tg://)\S+$", u) else None


def _throttled(kind: str, chat_id: int, seconds: int = 8) -> bool:
    now = time.time()
    if len(_last) > 5000:
        _last.clear()
    if now - _last.get((kind, chat_id), 0) < seconds:
        return True
    _last[(kind, chat_id)] = now
    return False


def _allowed(chat_id: int) -> bool:
    """Respect the allowed-groups list and the index chats if this project has them."""
    if hasattr(db, "group_allowed") and not db.group_allowed(chat_id):
        return False
    return not (hasattr(db, "is_connected") and db.is_connected(chat_id))


def _banned(uid: int) -> bool:
    return bool(hasattr(db, "is_banned") and db.is_banned(uid))


def _media_of(m):
    if not m:
        return None
    if m.photo:
        return {"type": "photo", "id": m.photo.file_id}
    if m.animation:
        return {"type": "animation", "id": m.animation.file_id}
    if m.video:
        return {"type": "video", "id": m.video.file_id}
    return None


def _keyboard(s: dict):
    rows = [[InlineKeyboardButton(b["t"], url=b["u"]) for b in row] for row in s.get("buttons", []) if row]
    if not rows:  # no custom buttons yet -> sensible defaults
        rows = [[InlineKeyboardButton("🔍 Open bot", url=f"https://t.me/{Config.BOT_USERNAME}")]]
        if getattr(Config, "WEBAPP_URL", ""):
            link = getattr(Config, "MINIAPP_LINK", "") or f"https://t.me/{Config.BOT_USERNAME}?start=app"
            rows.append([InlineKeyboardButton("🚀 Open Mini App", url=link)])
    return InlineKeyboardMarkup(rows)


# ---------------- settings storage ----------------
async def _settings(chat_id: int) -> dict:
    s = _cache.get(chat_id)
    if s is None:
        s = {}
        if hasattr(db, "get_meta"):
            try:
                s = await db.get_meta(f"welcome:{chat_id}", {}) or {}
            except Exception:
                s = {}
        _cache[chat_id] = s
    return s


async def _save(chat_id: int, s: dict):
    _cache[chat_id] = s
    if hasattr(db, "set_meta"):
        try:
            await db.set_meta(f"welcome:{chat_id}", s)
        except Exception:
            pass


async def _schedule(chat_id: int, message_id: int):
    if AUTO_DELETE > 0 and hasattr(db, "schedule_delete"):
        await db.schedule_delete(chat_id, message_id, AUTO_DELETE)


# ---------------- sending ----------------
async def _count(client, chat_id: int, template: str) -> str:
    if "{count}" not in template:
        return "?"
    try:
        return str(await client.get_chat_members_count(chat_id))
    except Exception:
        return "?"


async def _send_welcome(client, chat, user, s: dict, plain: bool = False):
    """Send the welcome for `user`. plain=True ignores the photo (used as a fallback)."""
    template = s.get("welcome_text") or DEFAULT_WELCOME
    text = _render(template, _vars(user, chat, await _count(client, chat.id, template)))
    kb = _keyboard(s)
    media = None if plain else s.get("media")
    if media:
        send = getattr(client, "send_" + media["type"])  # send_photo / send_animation / send_video
        sent = await send(chat.id, media["id"], caption=text, reply_markup=kb)
    else:
        sent = await client.send_message(chat.id, text, reply_markup=kb, disable_web_page_preview=True)
    await _schedule(chat.id, sent.id)  # removed after AUTO_DELETE seconds
    return sent


async def _reply(message, text: str):
    """Reply to an admin command; both vanish after AUTO_DELETE."""
    sent = await message.reply_text(text, disable_web_page_preview=True)
    await _schedule(sent.chat.id, sent.id)
    await _schedule(message.chat.id, message.id)
    return sent


# ---------------- new member / member left ----------------
@Client.on_message(filters.new_chat_members & filters.group, group=3)
async def on_join(client, message):
    chat = message.chat
    if not _allowed(chat.id):
        return
    users = [u for u in message.new_chat_members if not u.is_bot and not _banned(u.id)]
    if not users:
        return
    s = await _settings(chat.id)
    if s.get("welcome") is False or _throttled("join", chat.id):
        return
    for u in users[:3]:  # one message per person, max 3 per join event
        try:
            await _send_welcome(client, chat, u, s)
        except Exception:
            try:  # e.g. broken formatting or an expired photo -> plain default welcome
                await _send_welcome(client, chat, u, {})
            except Exception:
                pass


@Client.on_message(filters.left_chat_member & filters.group, group=3)
async def on_leave(client, message):
    chat, user = message.chat, message.left_chat_member
    if not user or user.is_bot or not _allowed(chat.id):
        return
    s = await _settings(chat.id)
    if s.get("goodbye") is False or _throttled("leave", chat.id):
        return
    template = s.get("goodbye_text") or DEFAULT_GOODBYE
    for t in (template, DEFAULT_GOODBYE):  # custom text first, default as a fallback
        try:
            sent = await client.send_message(chat.id, _render(t, _vars(user, chat, "?")), disable_web_page_preview=True)
            await _schedule(chat.id, sent.id)
            return
        except Exception:
            continue


# ---------------- admin controls ----------------
async def _can_edit(client, message) -> bool:
    if not _allowed(message.chat.id):
        return False
    u = message.from_user
    if u and u.id in Config.ADMINS:
        return True
    if message.sender_chat and message.sender_chat.id == message.chat.id:  # anonymous group admin
        return True
    if not u:
        return False
    try:
        m = await client.get_chat_member(message.chat.id, u.id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def _status(s: dict) -> str:
    def on(key):
        return "✅ ON" if s.get(key) is not False else "⏸ OFF"

    extras = [x for x in ("photo/GIF/video" if s.get("media") else "", f"{sum(len(r) for r in s.get('buttons', []))} buttons" if s.get("buttons") else "") if x]
    return (
        "⚙️ <b>WELCOME SETTINGS</b>\n"
        f"• <b>Welcome:</b> {on('welcome')} ({'custom text' if s.get('welcome_text') else 'default text'}"
        + (", " + ", ".join(extras) if extras else "") + ")\n"
        f"• <b>Goodbye:</b> {on('goodbye')} ({'custom text' if s.get('goodbye_text') else 'default text'})\n\n"
        "<code>/welcome on|off</code> · <code>/goodbye on|off</code>\n"
        "<code>/setwelcome text</code> - or reply to a text / photo / GIF / video with <code>/setwelcome</code>\n"
        "<code>/setgoodbye text</code> · add <code>reset</code> to restore the default\n"
        "<code>/delwelcomephoto</code> · <code>/testwelcome</code> (preview)\n"
        "<code>/addbutton Support | https://t.me/yoursupport</code> (+ <code>| same</code> = same row)\n"
        "<code>/buttons</code> · <code>/delbutton 1</code> · <code>/clearbuttons</code>\n\n"
        "<b>Placeholders:</b> <code>{mention}</code> <code>{first}</code> <code>{last}</code> <code>{fullname}</code> "
        "<code>{username}</code> <code>{id}</code> <code>{group}</code> <code>{count}</code>"
    )


async def _toggle(client, message, key: str, label: str):
    if not await _can_edit(client, message):
        return
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    s = await _settings(message.chat.id)
    if arg not in ("on", "off"):
        return await _reply(message, _status(s))
    s[key] = arg == "on"
    await _save(message.chat.id, s)
    await _reply(message, f"{'✅' if arg == 'on' else '⏸'} {label} message is now <b>{arg.upper()}</b> in this group.")


@Client.on_message(filters.command("welcome") & filters.group)
async def welcome_toggle(client, message):
    await _toggle(client, message, "welcome", "Welcome")


@Client.on_message(filters.command("goodbye") & filters.group)
async def goodbye_toggle(client, message):
    await _toggle(client, message, "goodbye", "Goodbye")


@Client.on_message(filters.command("setwelcome") & filters.group)
async def set_welcome(client, message):
    if not await _can_edit(client, message):
        return
    chat_id = message.chat.id
    s = await _settings(chat_id)
    old = dict(s)
    if len(message.command) > 1 and message.command[1].lower() == "reset":
        s.pop("welcome_text", None)
        s.pop("media", None)
        await _save(chat_id, s)
        return await _reply(message, "♻️ Welcome text and photo reset to the default.")

    src = message.reply_to_message
    own = message.caption.html if message.caption else (message.text.html if message.text else "")
    parts = own.split(None, 1)
    template = parts[1].strip() if len(parts) > 1 else ""
    media = _media_of(message) or _media_of(src)  # a photo in the command itself, or in the message replied to
    if not template and src and (src.text or src.caption):
        template = (src.text or src.caption).html
    if not template and not media:
        return await _reply(
            message,
            "Usage: <code>/setwelcome your text</code>, or reply to a text / photo / GIF / video with <code>/setwelcome</code>.\n"
            "Placeholders: <code>{mention}</code> <code>{first}</code> <code>{last}</code> <code>{fullname}</code> "
            "<code>{username}</code> <code>{id}</code> <code>{group}</code> <code>{count}</code>",
        )

    if media:
        s["media"] = media
    limit = 900 if s.get("media") else 3500  # a photo caption can only hold ~1000 characters
    if template:
        if len(template) > limit:
            _cache[chat_id] = old
            return await _reply(message, f"❌ Too long ({len(template)} characters). With a photo the limit is {limit}.")
        s["welcome_text"] = template

    if message.from_user:  # show the result right away; if Telegram rejects it, nothing is saved
        try:
            await _send_welcome(client, message.chat, message.from_user, s)
        except Exception:
            _cache[chat_id] = old
            return await _reply(message, "❌ Telegram couldn't send that (broken formatting?). Nothing was changed.")
    await _save(chat_id, s)
    await _reply(message, "✅ <b>Welcome message saved.</b> The message above is how new members will see it.")


@Client.on_message(filters.command("delwelcomephoto") & filters.group)
async def del_photo(client, message):
    if not await _can_edit(client, message):
        return
    s = await _settings(message.chat.id)
    had = s.pop("media", None)
    await _save(message.chat.id, s)
    await _reply(message, "🗑 Welcome photo removed." if had else "ℹ️ There was no welcome photo.")


@Client.on_message(filters.command("setgoodbye") & filters.group)
async def set_goodbye(client, message):
    if not await _can_edit(client, message):
        return
    s = await _settings(message.chat.id)
    if len(message.command) > 1 and message.command[1].lower() == "reset":
        s.pop("goodbye_text", None)
        await _save(message.chat.id, s)
        return await _reply(message, "♻️ Goodbye text reset to the default.")
    src = message.reply_to_message
    parts = (message.text.html if message.text else "").split(None, 1)
    template = parts[1].strip() if len(parts) > 1 else ((src.text or src.caption).html if src and (src.text or src.caption) else "")
    if not template:
        return await _reply(message, "Usage: <code>/setgoodbye your text</code> (or reply to a message). Same placeholders as the welcome.")
    s["goodbye_text"] = template[:1500]
    await _save(message.chat.id, s)
    await _reply(message, "✅ Goodbye text saved.")


@Client.on_message(filters.command("testwelcome") & filters.group)
async def test_welcome(client, message):
    if not await _can_edit(client, message) or not message.from_user:
        return
    s = await _settings(message.chat.id)
    await _schedule(message.chat.id, message.id)
    try:
        await _send_welcome(client, message.chat, message.from_user, s)
    except Exception:
        await _reply(message, "❌ The saved welcome can't be sent (broken formatting or expired photo). Set it again.")


# ---------------- buttons ----------------
def _flat(s: dict):
    return [(r, i) for r, row in enumerate(s.get("buttons", [])) for i in range(len(row))]


@Client.on_message(filters.command("addbutton") & filters.group)
async def add_button(client, message):
    if not await _can_edit(client, message):
        return
    raw = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    parts = [p.strip() for p in raw.split("|")]
    url = _clean_url(parts[1]) if len(parts) > 1 else None
    if not parts[0] or not url:
        return await _reply(message, "Usage: <code>/addbutton Support | https://t.me/yoursupport</code>\nAdd <code>| same</code> to put it next to the previous button.")
    s = await _settings(message.chat.id)
    rows = s.setdefault("buttons", [])
    same = len(parts) > 2 and parts[2].lower() in ("same", "row", "+")
    if len(_flat(s)) >= MAX_BUTTONS:
        return await _reply(message, f"❌ Maximum {MAX_BUTTONS} buttons. Remove one with /delbutton.")
    btn = {"t": parts[0][:40], "u": url}
    if same and rows and len(rows[-1]) < MAX_PER_ROW:
        rows[-1].append(btn)
    elif len(rows) >= MAX_ROWS:
        return await _reply(message, f"❌ Maximum {MAX_ROWS} rows. Use <code>| same</code> or remove a button.")
    else:
        rows.append([btn])
    await _save(message.chat.id, s)
    await _reply(message, f"✅ Button added ({len(_flat(s))} total). Check it with /testwelcome.")


@Client.on_message(filters.command("buttons") & filters.group)
async def list_buttons(client, message):
    if not await _can_edit(client, message):
        return
    s = await _settings(message.chat.id)
    flat = _flat(s)
    if not flat:
        return await _reply(message, "No custom buttons - the default ones (Open bot / Mini App) are used.")
    lines = [f"{n}. {_esc(s['buttons'][r][i]['t'])} - {_esc(s['buttons'][r][i]['u'])}" for n, (r, i) in enumerate(flat, 1)]
    await _reply(message, "🔘 <b>Welcome buttons</b>\n" + "\n".join(lines) + "\n\n<code>/delbutton 1</code> removes one.")


@Client.on_message(filters.command("delbutton") & filters.group)
async def del_button(client, message):
    if not await _can_edit(client, message):
        return
    s = await _settings(message.chat.id)
    flat = _flat(s)
    arg = message.command[1] if len(message.command) > 1 else ""
    if not arg.isdigit() or not 1 <= int(arg) <= len(flat):
        return await _reply(message, "Usage: <code>/delbutton 2</code> (see numbers with /buttons).")
    r, i = flat[int(arg) - 1]
    s["buttons"][r].pop(i)
    s["buttons"] = [row for row in s["buttons"] if row]
    await _save(message.chat.id, s)
    await _reply(message, "🗑 Button removed.")


@Client.on_message(filters.command("clearbuttons") & filters.group)
async def clear_buttons(client, message):
    if not await _can_edit(client, message):
        return
    s = await _settings(message.chat.id)
    s.pop("buttons", None)
    await _save(message.chat.id, s)
    await _reply(message, "🧹 Custom buttons cleared - default buttons are used again.")
