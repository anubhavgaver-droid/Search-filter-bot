from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardMarkup

import database as db
import guards
import texts
from config import Config
from delivery import miniapp_button, reply_temp
from richmsg import Btn


@Client.on_message(filters.command(["app", "miniapp"]))
async def open_app(client, message):
    if guards.group_blocked(message):
        return
    await db.schedule_delete(message.chat.id, message.id, Config.AUTO_DELETE)
    btn = miniapp_button(message.chat.type == ChatType.PRIVATE)
    if not btn:
        return await reply_temp(message, "⚠️ Mini App isn't configured yet (BASE_URL missing).")
    if message.chat.type == ChatType.PRIVATE:  # a real Mini App button only works as a normal inline button
        return await reply_temp(message, texts.miniapp_card(), InlineKeyboardMarkup([[btn]]))
    link = Config.MINIAPP_LINK or f"https://t.me/{Config.BOT_USERNAME}?start=app"
    await reply_temp(message, texts.miniapp_card(), [[Btn("🚀 Open Mini App", url=link, style="success")]])
