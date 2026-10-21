"""
check_install.py — verify every library SentinelEdge needs can be imported.
Used by FIRST_TIME_SETUP.bat. Exit code 0 = all present; otherwise lists what is missing.
"""

import importlib
import sys

# import name -> pip package (as in requirements.txt)
REQUIRED = {
    "fastapi": "fastapi", "starlette": "starlette", "uvicorn": "uvicorn[standard]", "websockets": "websockets",
    "pywebpush": "pywebpush", "dotenv": "python-dotenv", "requests": "requests", "pydantic": "pydantic",
    "firebase_admin": "firebase-admin", "psycopg2": "psycopg2-binary", "slowapi": "slowapi", "bcrypt": "bcrypt",
    "pyotp": "pyotp", "sentry_sdk": "sentry-sdk[fastapi]", "openpyxl": "openpyxl", "xlrd": "xlrd",
    "olefile": "olefile", "win32api": "pywin32", "email_validator": "email-validator",
    "multipart": "python-multipart", "cryptography": "cryptography", "serial": "pyserial",
}


def main() -> int:
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except Exception as exc:                      # not installed, or installed but broken
            missing.append((mod, pkg, exc.__class__.__name__))
    if not missing:
        print("All required libraries are installed.")
        return 0
    print("Missing / broken libraries:")
    for mod, pkg, why in missing:
        print(f"   {pkg}   (import {mod}: {why})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
