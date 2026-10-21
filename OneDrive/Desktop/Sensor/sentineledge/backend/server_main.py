"""
server_main.py — start the SentinelEdge server.

This is the entry point of the compiled program (sentineledge_server.exe). It can also be
run with plain Python:  python server_main.py   (same as  python -m uvicorn main:app).
"""

import os
import sys


def run() -> None:
    import uvicorn

    import config
    from main import app

    host = os.environ.get("SERVER_BIND", "0.0.0.0")
    port = int(os.environ.get("SERVER_PORT") or getattr(config, "SERVER_PORT", 5000) or 5000)
    # the app object is passed directly (no "main:app" string), so it works when compiled
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
    run()
