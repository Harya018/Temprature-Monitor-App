"""
Run this script on the other laptop AFTER robocopy to apply all pending fixes.
Usage (from CMD):
    cd /d D:\sensor\sentineledge
    python patch_other_laptop.py
"""
import os

BASE = r"D:\sensor\sentineledge"

def patch(rel_path, old, new, label):
    path = os.path.join(BASE, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if old in content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old, new, 1))
        print(f"  FIXED  {label}")
    elif new in content:
        print(f"  ALREADY OK  {label}")
    else:
        print(f"  NOT FOUND   {label}  — check manually")

print("Applying patches...\n")

# ── Fix 1: main.py — escape % in LIKE query ───────────────────────────────────
patch(
    r"backend\main.py",
    old="WHERE key LIKE 'proserver_%'",
    new="WHERE key LIKE 'proserver_%%'",
    label="main.py — LIKE query %% escape",
)

# ── Fix 2: admin.py — escape % in LIKE query ─────────────────────────────────
patch(
    r"backend\routers\admin.py",
    old="WHERE key LIKE 'proserver_%'",
    new="WHERE key LIKE 'proserver_%%'",
    label="admin.py — LIKE query %% escape",
)

print("\nDone. Now restart the server:  START.bat")
print("Then go to Admin → Settings → Pro-Server EX and save the file path again.")
