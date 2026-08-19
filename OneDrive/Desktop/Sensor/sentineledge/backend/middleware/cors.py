"""
middleware/cors.py — CORS configuration helper.

Origins are read from the ALLOWED_ORIGINS env var (comma-separated).
Falls back to ["*"] only in non-production environments so the LAN
dashboard still works during development without explicit config.

Production: set ALLOWED_ORIGINS=https://yourdomain.com,https://admin.yourdomain.com
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def configure_cors(app: FastAPI) -> None:
    raw = os.getenv("ALLOWED_ORIGINS", "").strip()
    app_env = os.getenv("APP_ENV", "development").lower()

    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
    elif app_env == "production":
        # In production with no explicit list, lock to same origin only
        origins = []   # CORSMiddleware with empty list rejects all cross-origin requests
    else:
        origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Auth-Token", "X-Admin-Password"],
    )
