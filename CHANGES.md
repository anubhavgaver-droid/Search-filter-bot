# Rich buttons update (v3 - every button)

Copy into your bot repo, same folders, replace when asked.

NEW      compat.py                   -> root   (Kurigram argument names)
NEW      richmsg.py                  -> root   (rich messages + automatic fallback)
REPLACE  bot.py                      -> root   (fix: use_qr error)
REPLACE  delivery.py                 -> root
REPLACE  notifier.py                 -> root
REPLACE  config.py                   -> root
REPLACE  requirements.txt            -> root   (pyrofork -> kurigram>=2.2.26)
REPLACE  plugins/search.py
REPLACE  plugins/library.py
REPLACE  plugins/start.py
REPLACE  plugins/story_requests.py
REPLACE  plugins/miniapp.py
REPLACE  plugins/admin.py
REPLACE  plugins/admin_tools.py
REPLACE  plugins/reports.py

Every button is now a rich message button (inside the bubble, colored):
- Users: search results, Back/Page/Next, Open post, Report broken link, Join / I've joined,
  /filters + genres, /request result, Get story notice, Mini App (PM and group), Search your own story
- Admin: report panel (Delete / Ignore / Add new link), request panel (Added / Reject),
  /groups remove buttons, /delete picker, "Test the new link"

Mini App button in PM uses Telegram's native blocks form (web_app buttons need it).
When an admin button is pressed the message is edited ("Added by ..."); the original text is
remembered in memory, and rebuilt from the database if the bot restarted in between.

Safety:
- If Telegram refuses a rich message, the bot sends the old normal buttons instead (see logs: "richmsg").
- Env RICH_BUTTONS=0 turns the rich look off without touching code.
