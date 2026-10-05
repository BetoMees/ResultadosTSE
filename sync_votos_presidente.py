#!/usr/bin/env python3
"""Baixa votos de Presidente (EA20) e grava no SQLite."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from urna_tse.db import Database
from urna_tse.votos import load_presidente_from_db, sync_presidente_to_db

DEFAULT_DB = ROOT / "data" / "urna_logs_6257.sqlite3"


def main() -> int:
    p = argparse.ArgumentParser(description="Sincroniza votos de Presidente no SQLite")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--ufs", nargs="*", help="UFs (além de br). Default: todas")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    db = Database(args.db)
    if args.ufs is None:
        from urna_tse.api import DEFAULT_UFS

        abrs = ["br"] + list(DEFAULT_UFS)
    else:
        abrs = ["br"] + [u.lower() for u in args.ufs]

    logging.info("Sincronizando votos Presidente para %s abrangências…", len(abrs))
    stats = sync_presidente_to_db(db, abrs=abrs)
    br = load_presidente_from_db(db, "br")
    logging.info("ok=%s fail=%s", stats["ok"], stats["fail"])
    if br and br.get("lider"):
        logging.info(
            "BR líder: %s (%s) %s votos",
            br["lider"]["nome"],
            br["lider"]["partido"],
            br["lider"]["votos"],
        )
    n_abr = db.count("votos_abr")
    n_cand = db.count("votos_candidatos")
    logging.info("SQLite: votos_abr=%s votos_candidatos=%s", n_abr, n_cand)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
