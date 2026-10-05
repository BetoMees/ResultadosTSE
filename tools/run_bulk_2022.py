"""Inicia import em massa 2022 (1º turno) em background."""
from __future__ import annotations

import logging
import time

from urna_tse.jobs import JOBS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
st = JOBS.start("2022-1t", store_blob=True)
print(st)
while True:
    s = JOBS.status()
    print(s.get("status"), s.get("message"))
    if s.get("status") not in ("running", "starting", "stopping"):
        print("FINAL", s)
        break
    time.sleep(15)
