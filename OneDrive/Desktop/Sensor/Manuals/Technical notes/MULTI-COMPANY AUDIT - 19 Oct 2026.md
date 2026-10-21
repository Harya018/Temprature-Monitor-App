# SentinelEdge: multi-company / multi-admin audit (19 Oct 2026)

Method: every one of the 300 API endpoints was called by Company A's admins using Company B's ids
(read, change, delete), with no login, and with a company login against the Super Admin area.
On top of that, 66 deployment cases were scripted: switching a company off, offboarding, admins
without a company, two companies with the same person, live websocket messages, owner-only tools.

## Found and fixed

| # | Severity | Problem | Fix |
|---|---|---|---|
| 1 | Critical | Any company admin's login could use every Super Admin function (create / switch off / delete companies, read all data). The session was matched to "any Super Admin exists", not to the logged-in person. Same fault in the 2FA setup/enforce/disable routes. | The session must belong to the Super Admin account itself (3 places). |
| 2 | Critical | A person in Company B's app could acknowledge Company A's alert by number. | Subscriber acknowledge now checks the alert's company; the name logged is the signed-in person's. |
| 3 | High | An admin or app user with no company (damaged / legacy row) was treated as "platform-wide" and saw every company's data, also on the live websocket. | Refused everywhere (API and websocket). Super Admin can no longer create a company admin without a company. |
| 4 | High | A switched-off company's admins kept working with their old session. | Locked out at once (API, websocket, app). |
| 5 | High | Live messages (acknowledgements, thresholds, Excel rows) were sent to every company's dashboards. | Each is sent only to the company it is about. |
| 6 | High | Simulate / import tools open to any company admin: fake breaches, and "import a CSV from a server path". | Super Admin only. |
| 7 | High | Test SMS / e-mail could be sent to any number or address with any text through the shared SIM / mail account. | Only to people on the company's own Subscribers list. |
| 8 | High | Mobile app: two companies with a person of the same name (or same PIN) could not log in correctly or could be mixed up. A disabled person could still log in and keep a 30-day session. | Every same-name account is checked; the same name + same PIN across companies is refused (409 when the PIN is set); disabling cuts the session at once. |
| 9 | Medium | Other companies could see / change the plant company's temperature limits, alert switches and pH range; reset thresholds; change the platform password; see collector readings, imported CSV history, whole-database size. | Plant-owner only; everyone else sees their own limits. |
| 10 | Medium | Offboarding left activity rows, kept the Excel / collector running under another company, left the removed company's dashboards connected and its files in the live folders. | Feeds are switched off, dashboards are disconnected, files are moved to data/offboarded. |
| 11 | Medium | A live feed whose owner was switched off or deleted fell back to the oldest company, so its readings would be stored under that company. | The feed belongs to nobody until a company takes it. |
| 12 | Low | The Super Admin "New admin" form defaulted to a role that cannot sign in and allowed no company. | Defaults to Company Admin, company required; sub-admins get a clear message at sign-in. |

## Test results (after the fixes)
- Cross-company fuzz, 298 endpoints x 2 roles: 0 data leaks, 0 cross-company changes, 0 Super Admin routes open to a company admin, 0 server errors.
- Deployment cases: 66/66.
- Regression: hub 70/70, node 52/52, four-company workflow 65/65, SRM + Elroi 14/14, live-data-only 10/10, pH-only 19/19, test-alert 11/11, alarm / open alert 9/9, new-laptop package 21/21.

## Known limits (not changed)
- The oldest active company on a PC counts as the "plant company" (backups, temperature engine, imported CSV history) unless Super Admin sets another. Fine for one company per laptop and for your hub; on a hub with many customers, set it deliberately.
- Sub-admin accounts exist but cannot sign in to the dashboard.
- Traffic is plain HTTP on the LAN / Tailscale; use Tailscale or a VPN between sites.
- The collector's shared key defaults to a built-in value (only accepted from this PC); set COLLECTOR_API_KEY on production.
- /docs and /openapi.json are open (they describe the API, they contain no data).
- Several companies cannot share one Excel reader at the same time (by design: one reader per PC).
