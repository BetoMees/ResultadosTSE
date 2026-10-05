#!/usr/bin/env python3
"""
Baixa logs da urna (log-da-urna) do portal público Resultados do TSE
e grava em SQLite, com retomada (resume), retries e limite de taxa.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from urna_tse.api import DEFAULT_UFS, TseResultadosClient
from urna_tse.db import Database
from urna_tse.downloader import UrnaLogDownloader

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "urna_logs_6257.sqlite3"


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Downloader de log da urna (TSE Resultados)")
    p.add_argument("--eleicao", default="6257", help="Código da eleição (default: 6257)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Caminho do SQLite")
    p.add_argument("--ufs", nargs="*", help="Filtrar UFs (ex.: ac sp). Default: todas")
    p.add_argument(
        "--workers",
        type=int,
        default=32,
        help="Downloads paralelos (default: 32; I/O-bound, ~2–3× cores)",
    )
    p.add_argument(
        "--min-interval",
        type=float,
        default=0.02,
        help="Intervalo mínimo entre *inícios* de request (s; default: 0.02)",
    )
    p.add_argument("--max-retries", type=int, default=8, help="Tentativas por request (default: 8; 429 espera mais)")
    p.add_argument("--limit", type=int, help="Limite total de itens (útil para teste)")
    p.add_argument(
        "--batch-size",
        type=int,
        default=2000,
        help="Processa aux+logs em lotes (default: 2000). Use 0 para fases únicas.",
    )
    p.add_argument(
        "--aux-refresh-seconds",
        type=float,
        default=1800.0,
        help=(
            "Reconsulta aux ok sem log só após este cooldown (s; default: 1800). "
            "Use 0 para reconsultar sempre (lento)."
        ),
    )
    p.add_argument("--skip-discover", action="store_true", help="Pula descoberta de seções (CS)")
    p.add_argument("--skip-aux", action="store_true", help="Pula download de aux.json")
    p.add_argument("--skip-logs", action="store_true", help="Pula download dos .jez")
    p.add_argument("--no-blob", action="store_true", help="Não guarda BLOB do .jez")
    p.add_argument(
        "--extract-text",
        action="store_true",
        help="Extrai logd.dat para a coluna log_text (aumenta muito o tamanho do DB)",
    )
    p.add_argument("--stats-only", action="store_true", help="Só mostra contagens do banco")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    db = Database(args.db)
    if args.stats_only:
        stats = db.stats()
        print(f"DB: {args.db}")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        for row in db.conn.execute("SELECT key, value FROM meta ORDER BY key"):
            print(f"  meta.{row['key']}={row['value']}")
        db.close()
        return 0

    client = TseResultadosClient(
        min_interval=args.min_interval,
        max_retries=args.max_retries,
    )
    dl = UrnaLogDownloader(
        db=db,
        client=client,
        eleicao=args.eleicao,
        workers=args.workers,
        store_blob=not args.no_blob,
        extract_text=args.extract_text,
        aux_refresh_seconds=args.aux_refresh_seconds,
    )

    ufs = [u.lower() for u in args.ufs] if args.ufs else None
    if ufs:
        unknown = sorted(set(ufs) - set(DEFAULT_UFS))
        if unknown:
            logging.warning("UFs fora da lista padrão: %s", ", ".join(unknown))

    try:
        dl.bootstrap()
        if not args.skip_discover:
            dl.discover(ufs)

        batch = args.batch_size
        total_budget = args.limit

        if batch and batch > 0:
            while True:
                if total_budget is not None and total_budget <= 0:
                    break
                chunk = batch if total_budget is None else min(batch, total_budget)
                n_aux = 0 if args.skip_aux else dl.download_aux(ufs, limit=chunk)
                n_logs = 0 if args.skip_logs else dl.download_logs(ufs, limit=chunk)
                logging.info("Lote concluído aux=%s logs=%s stats=%s", n_aux, n_logs, db.stats())
                if total_budget is not None:
                    total_budget -= chunk
                if n_aux == 0 and n_logs == 0:
                    break
        else:
            if not args.skip_aux:
                dl.download_aux(ufs, limit=total_budget)
            if not args.skip_logs:
                dl.download_logs(ufs, limit=total_budget)

        stats = db.stats()
        logging.info("Concluído. DB=%s stats=%s", args.db, stats)
        print(f"DB: {args.db}")
        for k, v in stats.items():
            print(f"  {k}: {v}")
    finally:
        client.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
