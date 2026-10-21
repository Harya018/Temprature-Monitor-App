# SentinelEdge - Final audit, 17 Oct 2026

## Result: all test suites pass (clean-install environment, isolated test schemas)
| Suite | Result |
|---|---|
| Hub + node lifecycle (pairing, sync, licence, outbox) | 70/70 |
| Company server (node) | 52/52 |
| Four-company workflow (own settings, parameters, logs, subscribers, reports) | 65/65 |
| SRM (collector) + Elroi (Excel) on the same PC | 14/14 |
| Live data only (no old/simulated data stored) | 10/10 |
| pH-only company | 19/19 |
| Test-alert button | 11/11 |
| Open alert / Acknowledge / pH-limit migration | 9/9 |
| Fresh-install package (no data, backups, secrets, logs, other companies) | 18/18 |
| Browser pages (every page, Edge) | 53/53 |
| Syntax of 123 backend files | 0 errors |
| Library check on a clean install | pass |

## Found and fixed during this audit
- A company's live-source owner was cached as "none" for 30 s, so a just-enabled source could be ignored. Fixed (never cache "none").
- Test runs wrote into the real project's logs/ and data/ folders. Fixed with COMPANY_LOG_DIR / READINGS_CSV_DIR overrides; leftovers removed.

## Needs action on the live system
1. Restart the real server (STOP.bat, START.bat). It was not running at audit time. The restart applies the one-time pH migration (SRM pH 0-14 -> 5.5-8.0), per-source owners and the sensor-silence fix.
2. Push the latest files to D: and copy to the other PC (backend + web build). 27 files differ on D:.
3. Rebuild the phone app (frontend-mobile) to get the silent "monitoring active" notification.

## Known limits
- Excel reader matches the agreed column layout; a free-format column mapping screen is not built.
- Pro-face compiled package: tools ready, nothing compiled.
- Super Admin has no self-service password change.
- Acknowledging at the hub does not reach the company server.
- SRM humidity / pressure / vibration have no limits set.
- Alert #1223 (13 Sept) was never acknowledged.
