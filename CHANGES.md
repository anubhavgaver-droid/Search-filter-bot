# Rich buttons update (v2)

Copy into your bot repo, same folders, replace when asked.

NEW      compat.py                   -> root   (fixes Kurigram argument names)
NEW      richmsg.py                  -> root   (rich message + automatic fallback)
REPLACE  bot.py                      -> root   (fix: unexpected keyword argument use_qr)
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

Fixed: TypeError "Message.reply() got an unexpected keyword argument 'disable_web_page_preview'"
(Kurigram renamed it; all files now use compat.NOPREVIEW).

Rich message (buttons inside the bubble): search results (group + PM), Back/Page/Next,
Open post, Report broken link, Join channel / I've joined, /filters + genres, /request
"already available", "Get story" notice, Mini App button in groups, "Search your own story".

Still normal inline buttons (on purpose): Mini App button in PM (needs the real web_app button),
and admin panels (report Delete/Ignore/Add link, request Added/Reject, /groups, /delete).

Env RICH_BUTTONS=0 switches the rich look off.
