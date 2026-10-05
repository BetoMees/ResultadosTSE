"""Sobe o dashboard de estatísticas em http://127.0.0.1:8765"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from web.app import DEFAULT_DB, app


def main() -> None:
    p = argparse.ArgumentParser(description="Dashboard de estatísticas dos logs da urna")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    app.state.db_path = args.db
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
