# SentinelEdge — Final Audit Report

Date: 16 Oct 2026. Scope: hub (Super Admin laptop) + company servers (nodes), data flow, workflows, error handling, clean-up.

## 1. How the production system works

| Part | Runs on | Own database | Role |
|---|---|---|---|
| **Hub** (`SERVER_ROLE=hub`, default) | Super Admin laptop (not always on) | Yes (`sentineledge`) | Super Admin, company set-up, approvals, licences, summaries from all companies. SRM is its local company. |
| **Company server** (`SERVER_ROLE=node`) | Each company's PC | Yes (its own PostgreSQL) | Collects and stores **every** reading, raises alerts, notifies its own people, serves the company admin dashboard. |

Link: the company server makes outgoing HTTP calls to the hub (Tailscale or LAN). No ports need opening on the company side.
Pairing: Super Admin generates a one-time code (24 h) → entered once at `http://localhost:5000/node-setup` on the company PC.

**Hub offline is normal.** Company servers keep collecting, alerting and storing. Alerts, acknowledgements, hourly summaries and parameter requests wait in a queue on the company server (up to 100,000 items) and are delivered, without duplicates, when the hub returns.

## 2. Your requirements → status

| Requirement | Status |
|---|---|
| Super Admin laptop is not on all the time; data is collected when it is on | **Done, tested** (store-and-forward through a hub outage, 0 lost, 0 duplicated) |
| Everything logged properly | **Done** — hub *Connection log* per company (paired, online, offline, data received, licence change, revoked, pairing code issued) + hub log file; company-side error shown on `/node-setup` |
| Admin side: all readings stored | **Fixed in this audit** — automatic deletion after 30 days was found and switched off (see 3.1) |
| Admin side: export for any dates | **Fixed in this audit** — silent 100,000-row cap removed (see 3.2) |
| New admin only created in Super Admin | **Fixed in this audit** — create / delete / change-password endpoints on the company side now return 403; page is read-only (see 3.3) |
| New company's admin must request parameters; Super Admin approves | **Done, tested** — request goes up, shows in Approvals, decision flows back, parameter appears on the dashboard live |
| Hub sees summaries, alerts, reports — not live data | **Done, tested** (hourly min/avg/max per parameter, alerts with acknowledgement, CSV) |
| Stop copying | **Partly** — hub-controlled licence done; compiled package not done (see 5) |

## 3. Problems found and fixed in this audit

1. **Readings were being deleted after 30 days** (two separate jobs; the oldest reading in the database was 13 Sep). Now readings are **kept forever**. The saved policy row is switched off by migration; Super Admin can still turn it on deliberately, and the setting `READINGS_RETENTION_DAYS` exists for the other job (0 = never delete). Alerts and audit logs were already kept forever.
2. **Reading export silently stopped at 100,000 rows** (about 2 days of data) and the second export omitted every parameter except temperature. Both now stream **all** rows for any date range, with every parameter as a column, in order and with no duplicates. Tested on 129,600 rows: all returned, 4.5 s. Dates are validated.
3. **Company admins could create/delete/reset other admins locally.** Those accounts would have been wiped by the next hub sync anyway; now refused with a clear message and the page is read-only.
4. **A brand-new database failed to initialise** (the schema cache kept the old table list, so `companies` columns were missing). Every new company server would have hit this. Fixed.
5. **Hub-address change had no remedy**: if the hub's LAN address changes, nodes would be stranded. Added "Change hub address" on `/node-setup` (no new code; PC only).
6. **Hub escalation engine would have re-notified synced alerts** from other companies. Synced alerts are excluded from escalation reminders and the global anomaly check.
7. Mis-quoted retention SQL in the policy job corrected.

## 4. Test evidence (isolated schemas; the real database was not touched)

Pairing (wrong code rejected, right code works, code is single-use) · heartbeat · outage queue and recovery (5 sent, 0 left, 5 on hub, 0 duplicates) · revoke → node stops · parameters, company status and admin logins pushed to node (node login with the hub-made password works) · node parameter request → hub approval → node dashboard · licence off / expired / hub unreachable beyond grace → node API returns 403, health stays up · alert + acknowledgement reach hub, escalation untouched · hourly summaries equal the readings (current partial hour correctly excluded) · export 129,600 rows · node offline/online in connection log · change hub address (bad address refused). All code compiles (118 files, 0 errors).

## 5. Open gaps and risks — read before the demo

**Must do**
- **Restart the hub** (STOP.bat → START.bat). The running server predates all of today's backend changes. The frontend is already rebuilt.
- **Pro-Server collector readings are still not stored or alerted** (they are only shown live). Turning that on would send real SMS/email, so it needs your decision. Excel-reader readings are stored and alerted.
- **Collector → GP4000_1 shows a network error** from this laptop (unresolved). Check the laptop and the HMI are on the same network before the demo.

**Should do**
- **Database is 2.8 GB for 1.5 M readings** — the table (1 GB) and its 5 overlapping indexes (1.7 GB) are bloated by past deletions. Running `VACUUM FULL readings` while the server is stopped would reclaim most of it; I did not run it without your approval. Readings now grow without limit (about 50 k rows/day here), so plan disk space.
- **Auto-start on boot** (PostgreSQL, backend, Tailscale, restart if it dies) is not built for company PCs. `PRODUCTION_SETUP.bat` exists for this laptop only; test a reboot before the demo.
- **Compiled package** for company installs is not built. Until then, whoever has the code can copy it and remove the licence check. The licence still protects you if you install it yourself, ship a compiled build, and keep a contract.
- **Plain HTTP on a LAN**: admin password hashes and data travel unencrypted unless the link is Tailscale (encrypted). Use Tailscale between sites.

**Known limitations (by design for now)**
- Acknowledging a remote alert on the hub does not reach the company server (acknowledgement only travels upward).
- Super Admin Overview / Analytics charts use the hub's own readings, so a remote company appears empty there; its data is in the company's *Summary* section. Up to 1 hour delay for summaries; alerts arrive in ~15 s.
- Super Admin broadcasts / maintenance messages to a company server are not yet pushed (company status and maintenance flag are).
- Temperature limit edits made by a company admin on its own server are not sent up to the hub.
- Hub and company clocks should be correct (summaries use UTC hours).
- The `/node-setup` page and pairing accept only this PC or local/Tailscale networks.
- The new Super Admin screens (Company server card, licence, summary, connection log) compile but were not looked at in a browser; the first thing to do after restart is open a company and check them.

## 6. Demo checklist

1. STOP.bat → START.bat on the hub; log in to Super Admin; confirm the tabs load.
2. Create a company (name, one parameter, main admin + password) — **Companies → company → Company server → Generate pairing code**.
3. On the second PC: `SERVER_ROLE=node` in `.env.production`, start, open `/node-setup`, enter hub address + code.
4. Within ~15 s the card shows **Online**; log in on the company PC with the password set in Super Admin.
5. Company admin requests a new parameter → Super Admin approves → appears on the company dashboard.
6. Feed a reading above the limit → alert on the company PC; within ~15 s it appears in Super Admin (Summary → recent alerts).
7. Stop the hub, create another alert, start the hub → it arrives (Connection log shows offline/online).
8. Reports → export a multi-day range as CSV.
9. Licence: untick *Allowed to run* → company PC is blocked within ~15 s; tick again.

## 7. Files removed

- 21 byte-identical `(1)` duplicates (scripts, guides, watchdog, installers); two with no original were renamed (`service_status.bat`, `setup_service.bat`).
- Generated listings: `structure.txt` (5.5 MB), `project_structure.txt`, and stray files `qc`, `query`.
- Stale copies of backend modules at the Sensor root: `escalation.py`, `sender.py`, `smtp.py`, `templates.py`.
- Dev leftovers: `backend/foundation/` (old step-by-step prototypes), `backend/demo/`, `backend/migrations/` (one-off), `main.py.backup`, `ticket.txt`, `uvicorn.log`, three old test-report logs, all `__pycache__` folders.

Kept on purpose: `sentineledge_backup.sql` (40 MB, 1 Aug backup — delete it yourself if you do not need it), `sms_dongle/` (GSM hardware code), `nssm.exe`, the rotated log files, all current scripts. Tracked files that were deleted can be restored from git; nothing has been committed.


---

# Part 2 — Full demo run (16 Oct 2026, after the first audit)

Everything below was run end to end on **my own temporary hub + company-server pair on throwaway database schemas** (your real database and running server were not touched; the schemas and processes were removed afterwards — real DB verified: 48 tables, 1 company, 1,508,754 readings, unchanged).

## Results

| Run | What it covered | Result |
|---|---|---|
| Hub lifecycle (API) | Super Admin creates company + admin + parameter; wizard enable; admin login / wrong password / lock / unlock / password reset; **parameter approval (approve, reject, duplicate, delete request)**; subscriber add / edit / disable / enable / duplicate order / delete; 60,000-row readings export (CSV, JSON, empty range, bad date, history export, alerts export, daily report); alert + acknowledge + ack-log; 6 Super Admin CSV exports; maintenance, message, broadcast, CRM note, company disable/enable, billing tier; **delete everything and compare with the starting state** | **70 / 70** — hub data tables identical to the start (only audit-log rows remain, by design) |
| Hub ↔ company server | Pairing; hub-made password works on the server; password reset / deactivate / reactivate sync; message + broadcast + maintenance reach the server's inbox; parameter add/remove on hub; **approval flow node → hub → node (approve, reject, delete)** with statuses matching on both sides; subscriber CRUD on the server (hub holds none); alerts + acknowledgement identical on both; **hourly summaries equal the server's own readings exactly (140 hour/parameter rows)**; hub summary + CSV; server exports (50,000 rows CSV, JSON, history, alerts, daily); every GET endpoint on the server; licence off/on; connection log; delete company while its server is paired; baseline restored | **52 / 52** |
| Real browser (Edge), every page | Company admin on the hub: 16 pages. Company admin on the company server: 16 pages. Super Admin: login, 19 sections plus all their sub-tabs, company detail for a local company and for a server-connected company (server card, summary, licence). JS errors, failed API calls, blank/crashed pages all counted as failures | **53 / 53** |
| GET sweep (all 157 hub / 55 server GET endpoints) | Server errors | 3 found and fixed (below); 0 remaining |

## Defects found in this demo and fixed

1. **Company delete failed half-way and left a half-deleted company** (it removed alerts and readings, then stopped on a foreign key from approval history). Now one all-or-nothing transaction that also clears approval history. This is the most important fix here.
2. **Company server dashboard showed other parameters** (Humidity, Pressure, Vibration, a second pH): with no real data source the server fell back to its built-in *simulated sensor*, stored fake readings, auto-created parameters and would have raised alerts and sent them to the hub. Company servers now ignore the simulated sensor completely and only store real data from their Excel / OPC source.
3. **Three server errors on a brand-new database** (Company detail page, Admin inbox, Scheduled broadcasts): a stale table list inside the database set-up. Fixed for every migration at once (new company servers would have hit these).
4. **Existing history was not reported on first sync**: the first summary run only looked back 48 h. It now starts from the server's oldest reading (up to a year).
5. **Super Admin broadcasts and direct messages never reached company servers**; now synced (with maintenance status).
6. **Company-server status listed all parameters/readings of every company on that PC**; now scoped to its own company.
7. **Settings page produced "403" errors for companies that don't own the sensor feed**; those calls are now only made by the owner.

## Behaviours you should know about (not defects, but worth a decision)

- **The hub itself still falls back to the simulated sensor** when no real source is active (that is how the SRM demo dashboard behaves today). It stores that simulated data under the sensor-owning company. If SRM must hold *only* real plant data, tell me and I will switch the simulation off for the hub too (one setting).
- **Exports use UTC dates.** "Export 16 Oct" means 16 Oct 00:00–23:59 UTC (05:30 IST to 05:29 IST next day). Readings are stored in UTC.
- **Login limits**: 10 attempts/minute per IP and a 15-minute lock after repeated wrong passwords (this is correct; it blocked my own polling test).
- A **broadcast** sent to all companies is not company-owned, so deleting a company does not remove it.
- Newly wizard-created companies stay **disabled until the wizard's final "enable" step** (the admin cannot log in before that).
- Two small test-only items I did *not* change: an unacknowledged-alert ack by Super Admin on the hub does not travel down to a company server; Overview/Analytics charts for server-connected companies stay empty (their data is in the Summary section).

## Status

Ready for the demo, subject to the "Must do" list in section 5 above: restart the hub; decide on Pro-Server collector storage (real SMS/email); check the GP4000_1 network from this laptop; test an auto-start on reboot. Nothing was committed.
