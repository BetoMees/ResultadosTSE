#!/usr/bin/env python3
"""Preenche votos_secao a partir do CSV odsele (cruza com modelo_urna dos logs)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from urna_tse.db import Database
from urna_tse.votos_csv import sync_votos_secao_from_csv

DEFAULT_DB = ROOT / "data" / "urna_logs_2022_1t.sqlite3"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--year", type=int, default=2022)
    p.add_argument("--turno", type=int, default=1, choices=(1, 2))
    p.add_argument("--zip", type=Path, help="ZIP votacao_secao local (opcional)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    db = Database(args.db)
    try:
        stats = sync_votos_secao_from_csv(
            db,
            year=args.year,
            turno=args.turno,
            zip_path=args.zip,
        )
        print(stats)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
