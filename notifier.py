import html


import database as db
import search_engine as engine
import texts
from config import Config
import richmsg
from delivery import deep_link
from richmsg import Btn


def admin_targets() -> list:
    return [Config.REQUEST_CHAT_ID] if Config.REQUEST_CHAT_ID else list(Config.ADMINS)


async def notify_request_result(client, r: dict, ok: bool, post=None) -> str:
    """Tell the requester (tagged in the group they asked from, else in PM). Returns a status line for admins."""
    chat_id = r.get("chat_id")
    in_group = bool(chat_id) and chat_id != r["user_id"]  # a private chat has the same id as the user
    rows = []
    if ok and post:
        rows = [[Btn("📖 Get story", url=deep_link(post["_id"], r["user_id"]), style="success")]]

    if in_group:
        try:
            mid = await richmsg.send(
                client,
                chat_id,
                texts.request_done(r["query"], ok, texts.mention_id(r["user_id"], r.get("user_name", "User"))),
                rows,
            )
            if Config.REQUEST_NOTICE_DELETE:
                await db.schedule_delete(chat_id, mid, Config.REQUEST_NOTICE_DELETE)
            return f"📣 tagged in <b>{html.escape(r.get('where', 'the group'))}</b>"
        except Exception:
            pass
    try:  # asked in PM (or the group message failed) -> PM, kept (not auto-deleted)
        await richmsg.send(client, r["user_id"], texts.request_done(r["query"], ok), rows)
        return "📩 notified in PM"
    except Exception:
        return "⚠️ <i>couldn't notify (hasn't started the bot)</i>"


async def fulfil_requests(client, post: dict) -> int:
    """A new story arrived: close matching pending requests (notifying the users) and old 'not found' entries."""
    title, tags = post["title"], post.get("hashtags", [])
    done = []
    for r in await db.pending_requests(200):
        if engine.pair_score(r["query"], title, tags, strict=True) >= Config.EXACT_SCORE:
            await db.set_request_status(str(r["_id"]), "auto-added")
            done.append((r, await notify_request_result(client, r, True, post)))

    gone = [m["_id"] for m in await db.top_misses(300) if engine.pair_score(m.get("q", ""), title, tags, strict=True) >= Config.EXACT_SCORE]
    await db.drop_misses(gone)

    if done:
        text = texts.auto_fulfilled(title, [(r["query"], r.get("user_name", "?"), info) for r, info in done])
        for t in admin_targets():
            try:
                await client.send_message(t, text)
            except Exception:
                pass
    return len(done)
