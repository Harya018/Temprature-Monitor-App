# SentinelEdge — Industrial IoT Monitoring System

A production-ready, self-hosted IoT monitoring and alert system for industrial sensor networks. Runs entirely on your local network — no cloud, no subscriptions.

---

## Features

- **Multi-parameter live monitoring** — Temperature, pH, Pressure, Humidity, Vibration, and custom parameters
- **Real-time WebSocket dashboard** — Live graphs, status cards, and instant breach alerts in the browser
- **Pro-Server EX / Excel sensor integration** — Reads live data directly from ProFace HMI `.xls` files via COM or xlrd
- **OPC DA support** — Direct connection to OPC DA servers for hardware sensor data
- **CSV data import** — Upload historical CSV files; analytics and graphs work automatically
- **Multi-tier alert system**:
  - In-app visual + audio alarm
  - Push notifications (web + mobile via VAPID)
  - Email alerts (Gmail SMTP)
  - SMS via Android GSM gateway
- **L1 → L2 → L3 escalation** — Automatically escalates unacknowledged alerts up the chain
- **Multi-company / Multi-admin** — SuperAdmin manages multiple companies; each company has its own admin and subscribers
- **Analytics dashboards** — Trend charts, anomaly detection, daily/hourly averages, breach frequency, channel delivery rates
- **Audit trail** — Full log of every setting change, alert, and acknowledgement
- **JWT authentication** — Separate login flows for SuperAdmin and company admins
- **Health scoring** — Per-company sensor health scores with configurable weights

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 · FastAPI · PostgreSQL · WebSockets |
| Web frontend | React 18 · Vite · Recharts |
| Mobile | React Native · Expo |
| Sensor integration | xlrd · openpyxl · Win32 COM (Pro-Server EX) |
| Auth | JWT · bcrypt · TOTP (2FA) |
| Push notifications | pywebpush · VAPID |
| Monitoring | Sentry |

---

## Project Structure

```
sentineledge/
├── backend/
│   ├── main.py                 # FastAPI app, WebSocket loop, sensor orchestration
│   ├── core/
│   │   ├── excel_sensor.py     # Pro-Server EX .xls live reader (COM + xlrd)
│   │   ├── opc_sensor.py       # OPC DA direct sensor reader
│   │   ├── extra_sensor.py     # Fallback random-drift values (humidity, vibration)
│   │   ├── sensor.py           # Base serial/CSV sensor
│   │   ├── threshold.py        # Breach detection
│   │   ├── escalation.py       # L1→L2→L3 escalation engine
│   │   └── anomaly_detector.py # Statistical anomaly detection
│   ├── routers/                # FastAPI route handlers (admin, analytics, alerts, …)
│   ├── database/
│   │   └── connection.py       # PostgreSQL connection + auto-migrations
│   └── modules/                # Email, SMS, push notification senders
├── frontend-web/               # React admin + super-admin dashboard
├── frontend-mobile/            # Expo React Native mobile app
├── database/                   # DB schema and seed scripts
├── scripts/                    # Utility and maintenance scripts
├── start.bat / start.sh        # One-command startup
└── stop.bat / stop.sh          # Graceful shutdown
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- (Optional) Pro-Server EX installed for live Excel sensor reading

### 1. Clone

```bash
git clone https://github.com/Harya018/Temprature-Monitor-App.git
cd Temprature-Monitor-App/sentineledge
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

Key variables:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/sentineledge
SECRET_KEY=your_jwt_secret_key

SMTP_USER=youremail@gmail.com
SMTP_PASSWORD=your_16_char_gmail_app_password

SMS_GATEWAY_URL=http://192.168.1.x:8080   # Android SMS gateway IP

VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_CLAIM_EMAIL=youremail@gmail.com
```

### 3. Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
python main.py
```

The server auto-runs all database migrations on first start.

### 4. Frontend

```bash
cd frontend-web
npm install
npm run build
```

The build output goes to `backend/static/` and is served automatically by FastAPI.

### 5. Open the dashboard

```
http://localhost:8000
```

---

## Pro-Server EX Sensor Setup

1. Go to **Admin → Settings → Pro-Server EX** in the dashboard
2. Enter the path to your `.xls` file (e.g. `C:\ProServer\data\readings.xls`)
3. Set column names matching your file headers (default: `DATE/TIME`, `TEMPERATURE`)
4. Click **Test** to verify the connection, then **Save**

The system automatically detects new rows appended to the file in real time (via COM session or file-size polling). Historical rows replay in **LOOP mode** (alerts suppressed); newly written rows run in **LIVE mode** (alerts fire).

---

## Analytics

The analytics page provides:

- **Live trend charts** — Temperature, pH over time
- **Daily / hourly averages** — Bar charts with configurable date range
- **Breach frequency** — How often thresholds are exceeded per day
- **Channel delivery rates** — Email, SMS, push success rates
- **Anomaly detection** — Z-score based outlier flagging
- **CSV import analytics** — Upload a CSV with historical data and get full chart coverage

---

## Alert Escalation

```
Breach detected
     │
     ▼  (immediate)
  Level 1 ── Email + SMS + Push → Subscribers
     │
     │  (60 s if unacknowledged)
     ▼
  Level 2 ── Repeat + Admin notified
     │
     │  (60 s if still unacknowledged)
     ▼
  Level 3 ── Repeat + SuperAdmin notified
     │
     └── Stops the moment anyone acknowledges
```

---

## SMS Setup (Android Gateway)

1. Install [android-sms-gateway](https://github.com/capcom6/android-sms-gateway) on an Android phone
2. Keep it on the same Wi-Fi network as the server
3. Set `SMS_GATEWAY_URL` in `.env` to the IP shown in the app

---

## Windows Service (Production)

```powershell
# Install as a Windows service (runs on boot, auto-restarts on crash)
.\install_service.ps1

# Check status
.\service_status.bat

# Remove service
.\uninstall_service.ps1
```

---

## License

MIT — use freely, modify freely, no warranty.
