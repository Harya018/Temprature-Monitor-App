# SentinelEdge: multi-company / multi-admin changes (as of 20 Oct 2026)

## A. Backend

### Architecture and data
- Hub / node roles: each company can run its own server (node) that pairs with the main (hub) server by a one-time code; heartbeat, store-and-forward outbox, licence gate, hub -> node sync of company, parameters and admins; node -> hub alerts and summaries.
- Per-company isolation: parameters (only approved ones are stored), limits and alerts on/off, activity log file, daily CSV tables, daily report, validator, anomaly detection, subscribers (1st / 2nd / 3rd contact per company), alert fan-out only to the company's own people.
- Live sources: the live collector and the Excel reader each belong to one company; a company can own both; Excel reads only NEW rows; no CSV / demo / simulated data is stored; pH-only companies supported (temperature optional).
- Offboarding a company deletes its data in one transaction, switches off its live feeds, disconnects its dashboards, moves its files to data/offboarded; a feed whose owner is switched off belongs to nobody (never to another company).

### Security (cross-company audit, 300 endpoints)
- A company admin could act as Super Admin (session was not tied to the Super Admin account): fixed in 3 places incl. 2FA routes.
- Subscriber could acknowledge another company's alert: fixed. People / admins with no company are refused (API + websocket); switched-off company locked out at once.
- Websocket and broadcast messages scoped per company; simulate / CSV-import tools Super Admin only; test SMS / e-mail only to the company's own subscribers; plant-company-only items (backup, thresholds, platform password, imported CSV history, DB size); analytics CSV history guarded.
- Mobile login: same name in two companies handled; same name + same PIN refused; disabled people lose the session.
- Super Admin can no longer create a company admin without a company.
- Sub-admins can now sign in (web and phone app) as READ-ONLY accounts: one rule in main.py blocks every change except acknowledging alerts; the web screens show "Read-only" and disable their fields.
- Super Admin chooses the main company of this PC (PUT /api/super-admin/sensor-company/plant); the server e-mail account (.env) follows it safely. Super Admin can change their own password (POST /api/super-admin/change-password; other sign-ins are signed out).

### New per-company features
- Alert wording: SMS text and e-mail (subject + body) per parameter, with placeholders; preview endpoint; unknown placeholder refused; SMS cut at 160 characters, plain characters only.
- E-mail account per company: company_email_settings table (password encrypted with a local key); the plant company's account is written into .env automatically and applied without restart; no default account and no fallback to another company's mailbox; test e-mail with plain error messages.
- Parameter limits and alerts on/off per company; "Send test alert" per parameter.
- Health: sensor status per company (Live / Excel Live / No Data / No Live Source); no CSV fallback.
- Real-data analytics: subscriber response rates use each person's own notifications and acknowledgements, only for active people; Super Admin counts only active subscribers.

### Phone app API (one app for every company)
- POST /api/app/login (subscriber name + PIN, or company admin), GET /api/app/config (company name + its parameters), GET /api/app/latest (latest value per parameter), GET /api/app/server-address.

### Tailscale
- GET /api/admin/tailscale (status + notice), PUT /api/admin/tailscale/invite, Super Admin GET/PUT /api/super-admin/tailscale; the saved link is sent to every company server in the heartbeat.

### Setup / packaging
- FIRST_TIME_SETUP: installs Python + PostgreSQL + libraries, random database password, asks for the Super Admin password (hidden, twice), no secrets in the package; requirements: email-validator, python-multipart, cryptography, pyserial.

## B. Frontend (web dashboard)

### Company admin
- Settings is built from the company's own parameters: limits + alerts on/off + "Send test alert" per parameter; "Alert messages" (one SMS form and one e-mail form per parameter, placeholder buttons, preview); "E-mail account for alerts" with step-by-step help per provider; "Phone app" card (server address); "Tailscale" card (status, steps, invitation link); SMS section explains the SIM7600 GSM modem; the old "Email Configuration" box was removed.
- Dashboard: one tile per company parameter; live counting clock / uptime / "x seconds ago"; open alerts and Acknowledge appear after a refresh.
- Notification bell: panel with unacknowledged alerts and system notices (turn on Tailscale / connect to the main server), opens once per sign-in, "Remind me later".
- Health page: sensor card shows Live / Excel Live / No Data / No Live Source.
- Analytics: subscriber response table shows real figures.
- Manage Admins is read-only (accounts are created by Super Admin).

### Super Admin
- Cards: "Live sources on this PC" (who owns the collector / Excel reader), "Tailscale" (paste the share link), node connection / licence / log views.
- New-admin form: defaults to Company Admin, company required; empty ack rate shows "-".

## C. Phone app (source changed, needs a new APK)
- Server address typed once on the sign-in screen (nothing built in); sign-in with name + PIN (or admin); websocket uses the token.
- Dashboard shows one card per company parameter with its own unit and limits; alerts and the alert screen name the real parameter; Acknowledge from the list; silent "monitoring active" notification; token header chosen by sign-in type.

## D. Still to do / decisions for you
- Rebuild the APK and test on a real phone with two companies.
- Test Tailscale between two real computers (the other PC was offline).
- Create the Tailscale share link (Machines -> Share, reusable, 30-day acceptance) and paste it in Super Admin.
- Push to D: and copy to the other PC; restart the real server.
- Firebase service-account file must be copied to each company server for direct FCM push (Expo push works without it).
## E. Also done in the last round
- Super Admin acknowledges a company's alert on the main server -> the company server's own copy is acknowledged too (queued on the hub, delivered with the next heartbeat, removed once the server confirms; shows "(main server)" as the acknowledger).
- Excel reader accepts differently named columns (case, spaces, "Value"/"Reading", unit in brackets; time columns found by name). Unattended servers now start reading Excel at boot (before, it only started when a dashboard was opened).
- API documentation pages (/docs, /redoc) are off by default (set ENABLE_DOCS=1 in a non-production setup to open them).

## F. Multi-admin loopholes closed
- Acknowledge: recorded under the signed-in admin's own name (a typed name is ignored); the first acknowledger is kept - a second admin (or Super Admin) gets "already acknowledged by X" and cannot overwrite the name/time/response time. Three admins clicking at once: exactly one wins.
- My Account (was "Admin Profile", which managed the plant PC's built-in login for everybody): shows the admin's own name, role and company and changes only their own password; only their other sign-ins end (before, changing it signed out every admin of every company). Sub-admins may change their own password. Company servers: password managed on the main server.
- verify-password checks the admin's own password (it checked the plant PC's built-in password).
- Logout ends the session on the server (before it only cleared the browser; the token stayed valid for 8 h). Same for the Super Admin panel.
- Open live dashboards / live logs re-check the sign-in every 15 s: switched off, password reset, signed out or moved to another company -> closed.
- Company server: a password reset / role change / switch-off from the main server ends that admin's sign-ins on the company server too.
- Built-in "admin" login (ADMIN_PASSWORD in the settings file) can no longer switch on an account that Super Admin switched off; it belongs to the PC's main company; its password change updates the settings file.
- Admin names unique ignoring capitals/spaces; "admin"/"superadmin" reserved; sign-in not case-sensitive.
- Moving an admin to another company: not allowed without a company or for the Super Admin; signs the admin out; recorded in the audit log.
- "Act as admin": recorded as "Super Admin (as <name>)"; ending it ends the session (it stayed valid up to 1 h).
- Activity log: every entry filed under the admin's company; subscriber switch-on/off and PIN changes logged; settings change history records the admin's name; deleting alert history records who did it.

## G. New-PC setup (one click)
- FIRST_TIME_SETUP.bat moved to the main folder (next to START.bat); the package puts it there too.
- One click: only the Windows Administrator "Yes" (plus the postgres password only if PostgreSQL was already installed). No Super Admin question, no "Start now?" - SentinelEdge starts by itself at the end.
- Super Admin password is the same standard password on every PC (set by setup; a second run resets an existing Super Admin to it and ends its old sign-ins). Only its bcrypt hash is in the setup script; the server stores that hash as it is - the password is not written in any file.
- The database passwords of the PC (postgres, database user) plus the dashboard addresses go into "SentinelEdge PASSWORDS - KEEP PRIVATE.txt" in the main folder (only Administrators / SYSTEM / the installing user can open it); it is opened in Notepad and the last message of setup names it. The package builder refuses any "passwords" file.
- Also: setup unblocks the copied files, opens port 5000 in the firewall, records the Python it used (START.bat uses it), only accepts Python 3.11/3.12 (pinned libraries); START.bat checks that setup was run, that Python + libraries work, and starts any installed PostgreSQL version.
- A database created WITHOUT FIRST_TIME_SETUP (PostgreSQL configured by hand) also gets the standard Super Admin password on the first start (the server no longer makes a random one-time password or prints it in the log). The hash lives in backend\utils\security.py and setup_secrets.ps1 only.
- sentineledge\tools\RESET_SUPERADMIN_PASSWORD.bat puts the standard password back on an installed PC (Super Admin only; its sign-ins end). Done on this main laptop on 21 Oct 2026; the other PC: run it there after copying the new files.
