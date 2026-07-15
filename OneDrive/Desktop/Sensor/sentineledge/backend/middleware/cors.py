"""
middleware/cors.py — CORS configuration helper.

Provides configure_cors() which adds CORSMiddleware to a FastAPI app.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def configure_cors(app: FastAPI) -> None:
    """Add permissive CORS headers (appropriate for local LAN deployments)."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
