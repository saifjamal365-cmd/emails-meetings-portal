"""Run the whole portal as one server, without a window (for auto-start at Windows login).

    .venv\\Scripts\\pythonw.exe run_portal.py     # no window
    .venv\\Scripts\\python.exe run_portal.py      # with a window, to see errors

The backend also serves the built portal (frontend/dist), so open http://localhost:8000.
Build the portal first after changes:  cd frontend && npm run build
The log is written to data/logs/portal.log (the last 3 files of 5 MB are kept).
"""

import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST, PORT = "127.0.0.1", 8000


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, PORT)) == 0


def main() -> None:
    sys.path.insert(0, str(HERE))
    # The portal is always at this address here, so Google's login comes back to it
    # even when .env has no FRONTEND_ORIGIN line (set by the Setup page or not).
    os.environ.setdefault("FRONTEND_ORIGIN", f"http://localhost:{PORT}")
    from app.config import get_settings  # after sys.path, so "app" is found

    logs = get_settings().data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "portal.log", maxBytes=5_000_000, backupCount=3,
                                  encoding="utf-8")  # fmt: skip
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    log = logging.getLogger("portal")

    if port_in_use():  # the portal (or something else) already runs on this port
        log.warning("Port %s is already in use - not starting a second portal.", PORT)
        return

    import uvicorn

    log.info("Starting the portal on http://localhost:%s", PORT)
    # log_config=None: uvicorn uses the log file above instead of a console.
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_config=None)


if __name__ == "__main__":
    main()
