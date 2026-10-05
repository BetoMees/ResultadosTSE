"""Cliente HTTP para endpoints públicos do portal Resultados (TSE)."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)


def json_loads(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))

DEFAULT_HOST = "https://resultados.tse.jus.br"
DEFAULT_AMBIENTE = "oficial"
DEFAULT_UFS = (
    "ac",
    "al",
    "am",
    "ap",
    "ba",
    "ce",
    "df",
    "es",
    "go",
    "ma",
    "mg",
    "ms",
    "mt",
    "pa",
    "pb",
    "pe",
    "pi",
    "pr",
    "rj",
    "rn",
    "ro",
    "rr",
    "rs",
    "sc",
    "se",
    "sp",
    "to",
    "zz",
)


def pad(value: Any, width: int) -> str:
    return str(value).zfill(width)


class TseResultadosClient:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        ambiente: str = DEFAULT_AMBIENTE,
        timeout: float = 60.0,
        max_retries: int = 5,
        backoff: float = 1.5,
        min_interval: float = 0.05,
        user_agent: str = "UrnaTSE-Downloader/1.0 (+pesquisa; dados publicos)",
    ) -> None:
        self.host = host.rstrip("/") + "/"
        self.ambiente = ambiente
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.min_interval = min_interval
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._local = threading.local()
        self.user_agent = user_agent

    def _session(self) -> requests.Session:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = requests.Session()
            sess.headers.update({"User-Agent": self.user_agent, "Accept": "*/*"})
            self._local.session = sess
        return sess

    def close(self) -> None:
        sess = getattr(self._local, "session", None)
        if sess is not None:
            sess.close()

    def _throttle(self) -> None:
        """Espaça o *início* dos requests sem segurar o lock durante o sleep.

        Assim vários workers podem estar em HTTP paralelo; só a taxa de
        disparo é limitada (evita serializar o pool em min_interval).
        """
        if self.min_interval <= 0:
            return
        wait = 0.0
        with self._lock:
            now = time.monotonic()
            wait = self._last_request + self.min_interval - now
            if wait > 0:
                self._last_request = now + wait
            else:
                self._last_request = now
                wait = 0.0
        if wait > 0:
            time.sleep(wait)

    def request_bytes(self, path_parts: list[str], allow_404: bool = True) -> tuple[int, bytes, str]:
        url = self.host + "/".join(str(p) for p in path_parts)
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session().get(url, timeout=self.timeout)
                if resp.status_code == 404 and allow_404:
                    return 404, resp.content, url
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.status_code, resp.content, url
            except (requests.RequestException, requests.HTTPError) as exc:
                last_err = exc
                sleep_s = self.backoff ** (attempt - 1)
                log.warning("Falha %s/%s em %s: %s; retry em %.1fs", attempt, self.max_retries, url, exc, sleep_s)
                time.sleep(sleep_s)
        raise RuntimeError(f"Falha ao baixar {url}: {last_err}")

    def request_json(self, path_parts: list[str], allow_404: bool = True) -> tuple[int, Any, str]:
        status, raw, url = self.request_bytes(path_parts, allow_404=allow_404)
        if status == 404:
            return status, None, url
        return status, json_loads(raw), url

    def ele_c(self) -> dict[str, Any]:
        _, data, _ = self.request_json([self.ambiente, "comum", "config", "ele-c.json"], allow_404=False)
        return data

    def resolve_election(self, eleicao: str | int) -> dict[str, Any]:
        """Retorna ciclo, pleito e metadados a partir do código da eleição (ex.: 6257)."""
        catalog = self.ele_c()
        target = str(eleicao)
        for pleito in catalog.get("pl", []):
            for ele in pleito.get("e", []):
                if str(ele.get("cd")) == target:
                    return {
                        "eleicao": target,
                        "eleicao_nome": ele.get("nm"),
                        "turno": ele.get("t"),
                        "pleito": str(pleito.get("cd")),
                        "ciclo": pleito.get("c"),
                        "data": pleito.get("dt"),
                        "raw_eleicao": ele,
                        "raw_pleito": pleito,
                    }
        raise ValueError(f"Eleição {eleicao} não encontrada em ele-c.json")

    def cs_url_parts(self, ciclo: str, pleito: str | int, uf: str) -> list[str]:
        uf = uf.lower()
        p = pad(pleito, 6)
        return [self.ambiente, ciclo, "arquivo-urna", str(pleito), "config", uf, f"{uf}-p{p}-cs.json"]

    def aux_url_parts(
        self,
        ciclo: str,
        pleito: str | int,
        uf: str,
        municipio: str | int,
        zona: str | int,
        secao: str | int,
    ) -> list[str]:
        uf = uf.lower()
        p = pad(pleito, 6)
        m = pad(municipio, 5)
        z = pad(zona, 4)
        s = pad(secao, 4)
        name = f"p{p}-{uf}-m{m}-z{z}-s{s}-aux.json"
        return [
            self.ambiente,
            ciclo,
            "arquivo-urna",
            str(pleito),
            "dados",
            uf,
            m,
            z,
            s,
            name,
        ]

    def arquivo_url_parts(
        self,
        ciclo: str,
        pleito: str | int,
        uf: str,
        municipio: str | int,
        zona: str | int,
        secao: str | int,
        hash_value: str,
        arquivo: str,
    ) -> list[str]:
        uf = uf.lower()
        return [
            self.ambiente,
            ciclo,
            "arquivo-urna",
            str(pleito),
            "dados",
            uf,
            pad(municipio, 5),
            pad(zona, 4),
            pad(secao, 4),
            hash_value,
            arquivo,
        ]

    def fetch_cs(self, ciclo: str, pleito: str | int, uf: str) -> tuple[int, Any, str]:
        return self.request_json(self.cs_url_parts(ciclo, pleito, uf))

    def fetch_aux(
        self,
        ciclo: str,
        pleito: str | int,
        uf: str,
        municipio: str | int,
        zona: str | int,
        secao: str | int,
    ) -> tuple[int, Any, str]:
        return self.request_json(self.aux_url_parts(ciclo, pleito, uf, municipio, zona, secao))

    def fetch_arquivo(
        self,
        ciclo: str,
        pleito: str | int,
        uf: str,
        municipio: str | int,
        zona: str | int,
        secao: str | int,
        hash_value: str,
        arquivo: str,
    ) -> tuple[int, bytes, str]:
        return self.request_bytes(
            self.arquivo_url_parts(ciclo, pleito, uf, municipio, zona, secao, hash_value, arquivo)
        )
