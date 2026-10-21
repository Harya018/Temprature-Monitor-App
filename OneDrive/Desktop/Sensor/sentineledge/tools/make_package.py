"""
make_package.py — build a clean copy of SentinelEdge for a NEW company's laptop.

Copies ONLY what a new laptop needs (an allow-list), so no company data, database
backups, CSV tables, logs, passwords, secrets, the Pro-face collector or source code
ever leave this PC.

    python make_package.py [target folder]
Default target: <Desktop>\\SentinelEdge_NewLaptop
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)                    # ...\sentineledge
ROOT = os.path.dirname(APP)                    # ...\Sensor (folder with START.bat)

# backend folders/files that are never shipped
SKIP_DIRS = {"__pycache__", "secrets", "data", "logs", "tests", "sms_dongle", "foundation", "demo",
             "migrations", "venv", "venv32", ".pytest_cache"}
SKIP_FILES = {"server.pid", "uvicorn.log", "ticket.txt"}
SKIP_EXT = {".pyc", ".pyo", ".backup", ".bak", ".log", ".sql", ".dump", ".map"}


def _ignore(directory, names):
    out = []
    for n in names:
        full = os.path.join(directory, n)
        if os.path.isdir(full):
            if n in SKIP_DIRS:
                out.append(n)
        elif n in SKIP_FILES or os.path.splitext(n)[1].lower() in SKIP_EXT:
            out.append(n)
    return out


def build(target: str) -> None:
    if os.path.exists(target):
        print(f"The folder already exists: {target}\nDelete or rename it first, then run again.")
        sys.exit(1)
    os.makedirs(target)
    # top level: FIRST_TIME_SETUP / START / STOP / manual + user manuals (not the technical notes)
    for f in ("FIRST_TIME_SETUP.bat", "START.bat", "STOP.bat", "USER MANUAL.txt"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(target, f))
    man_src, man_dst = os.path.join(ROOT, "Manuals"), os.path.join(target, "Manuals")
    os.makedirs(man_dst)
    for f in sorted(os.listdir(man_src)):
        p = os.path.join(man_src, f)
        if os.path.isfile(p) and f.lower().endswith(".txt"):
            shutil.copy2(p, os.path.join(man_dst, f))
    # program
    app_dst = os.path.join(target, "sentineledge")
    os.makedirs(app_dst)
    shutil.copytree(os.path.join(APP, "backend"), os.path.join(app_dst, "backend"), ignore=_ignore)
    for f in ("setup_prereqs.ps1", "setup_secrets.ps1", ".env.template"):
        shutil.copy2(os.path.join(APP, f), os.path.join(app_dst, f))

    # safety check: nothing private slipped through
    bad = []
    for d, dirs, files in os.walk(target):
        for n in dirs + files:
            low = n.lower()
            if low in ("secrets", "venv", "venv32", "collector", "frontend-web", "frontend-mobile", "backups") \
                    or "passwords" in low or low == "python_path.txt" \
                    or low.startswith(".env.") and low != ".env.template" or low.endswith((".sql", ".dump", ".csv")):
                bad.append(os.path.join(d, n))
    if bad:
        print("REFUSING - private files found in the package:\n  " + "\n  ".join(bad))
        shutil.rmtree(target)
        sys.exit(1)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(target) for f in fs)
    print(f"Package ready: {target}  ({size / 1024 / 1024:.1f} MB)")
    print("Copy this folder to the new laptop, double-click FIRST_TIME_SETUP.bat in it and follow")
    print("Manuals\\1 - Install on a new laptop.txt")


if __name__ == "__main__":
    default = os.path.join(os.path.expanduser("~"), "Desktop", "SentinelEdge_NewLaptop")
    build(os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else default)
