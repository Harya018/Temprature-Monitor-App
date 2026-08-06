# SentinelEdge — Deployment Guide

This guide covers production deployment on a Windows Server or industrial PC.

---

## Prerequisites

| Component  | Minimum Version | Notes |
|------------|-----------------|-------|
| Python     | 3.11            | Add to PATH during install |
| PostgreSQL | 14              | Add `bin` folder to PATH |
| Node.js    | 18              | For building the frontend |
| NSSM       | 2.24+           | For Windows service install |

---

## First-Time Setup

Run the automated setup script from the project root:

```bat
.\setup.bat
```

This will:
1. Create a Python virtual environment and install backend dependencies
2. Copy `.env.example` → `.env.development` (edit before starting)
3. Create the PostgreSQL database and user
4. Install frontend Node dependencies and build the production bundle

---

## Environment Configuration

Edit `.env.development` (or `.env.production`) with your values:

| Variable          | Required | Description |
|-------------------|----------|-------------|
| `DATABASE_URL`    | Yes      | PostgreSQL connection string |
| `ADMIN_PASSWORD`  | Yes      | Change from default |
| `SMTP_USER`       | Yes (email alerts) | Gmail address |
| `SMTP_PASSWORD`   | Yes (email alerts) | Gmail App Password |
| `SMS_METHOD`      | Yes (SMS alerts) | `adb`, `gammu`, `gateway`, or `sim7600` |
| `DEMO_MODE`       | Yes      | `false` for live sensor, `true` for CSV replay |
| `SENSOR_PORT`     | If DEMO_MODE=false | COM port of USB temp sensor |
| `VAPID_PUBLIC_KEY`| Yes (push) | Generate with `python -m py_vapid --gen` |
| `VAPID_PRIVATE_KEY`| Yes (push) | Same command |

---

## Starting the Server

**Development:**
```bat
.\start.bat
```

**Production (with watchdog):**
```bat
.\start_production.bat
```

---

## Installing as a Windows Service

Requires NSSM (Non-Sucking Service Manager):

```bat
.\install_service.ps1
```

Useful service commands:
```bat
nssm start SentinelEdge
nssm stop SentinelEdge
nssm restart SentinelEdge
.\service_status.bat
```

---

## PostgreSQL Backup (Automated)

A nightly backup script ships with the project. Configure rclone (Google Drive):

```bat
rclone config       # follow prompts to add Google Drive remote named "gdrive"
.\scripts\backup_postgres.bat   # test manual backup
```

The `install_autostart.bat` script registers the backup as a scheduled task.

---

## Subscription Tiers

Tier enforcement is automatic. To assign a tier to a company:

1. Log in as super admin at `http://<host>:<port>/super-admin`
2. Navigate to **Billing → Usage Dashboard**
3. Use **Assign Tier** to set the tier for any company

Default tiers (editable in the database):

| Tier | Subscribers | SMS/month | Email/month |
|------|-------------|-----------|-------------|
| Basic | 50 | 100 | 500 |
| Professional | 200 | 500 | 2000 |

---

## Onboarding New Companies

1. Super Admin → **Companies** → Create company
2. Super Admin → **Onboarding** → Select company → **Initialise Onboarding**
3. Walk through the 5 steps with the client:
   - Company Profile (auto-complete)
   - Add First Subscriber
   - Configure Escalation Policy
   - Test Breach Alert (trigger simulated breach)
   - Go Live

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Server won't start | Missing `.env` file | Run `setup.bat` |
| SMS not sending | Wrong `SMS_METHOD` or modem not connected | Check device manager for COM port |
| Email not sending | App Password not set | Enable 2FA on Gmail, generate App Password |
| Sensor data frozen | Wrong `SENSOR_PORT` | Check device manager; update `.env` |
| DB connection error | PostgreSQL not running | `net start postgresql-x64-14` |
