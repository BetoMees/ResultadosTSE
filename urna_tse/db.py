"""Esquema SQLite para metadados e conteúdo dos logs da urna."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional



SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS uf_config (
    uf TEXT PRIMARY KEY,
    nome TEXT,
    cdp TEXT,
    dg TEXT,
    hg TEXT,
    n_secoes INTEGER,
    http_status INTEGER,
    raw_json TEXT,
    downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS secoes (
    id INTEGER PRIMARY KEY,
    uf TEXT NOT NULL,
    municipio_cd TEXT NOT NULL,
    municipio_nm TEXT,
    zona TEXT NOT NULL,
    secao TEXT NOT NULL,
    data_apuracao TEXT,
    hora_apuracao TEXT,
    modelo_urna TEXT,
    UNIQUE(uf, municipio_cd, zona, secao)
);

CREATE TABLE IF NOT EXISTS aux (
    secao_id INTEGER PRIMARY KEY REFERENCES secoes(id),
    http_status INTEGER,
    st TEXT,
    raw_json TEXT,
    error TEXT,
    downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS cargas (
    id INTEGER PRIMARY KEY,
    secao_id INTEGER NOT NULL REFERENCES secoes(id),
    hash TEXT NOT NULL,
    st TEXT,
    dr TEXT,
    hr TEXT,
    UNIQUE(secao_id, hash)
);

CREATE TABLE IF NOT EXISTS arquivos (
    id INTEGER PRIMARY KEY,
    carga_id INTEGER NOT NULL REFERENCES cargas(id),
    secao_id INTEGER NOT NULL REFERENCES secoes(id),
    tipo TEXT NOT NULL,
    nome TEXT NOT NULL,
    url TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    content BLOB,
    log_text TEXT,
    modelo_urna TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    downloaded_at TEXT,
    UNIQUE(carga_id, tipo, nome)
);

CREATE TABLE IF NOT EXISTS votos_abr (
    abr TEXT PRIMARY KEY,
    eleicao TEXT,
    cargo TEXT,
    turno TEXT,
    atualizado_em TEXT,
    secoes_totalizadas INTEGER,
    secoes_total INTEGER,
    secoes_totalizadas_pct TEXT,
    eleitorado_aptos INTEGER,
    votos_total INTEGER,
    votos_validos INTEGER,
    votos_brancos INTEGER,
    votos_nulos INTEGER,
    abstencoes INTEGER,
    raw_json TEXT,
    downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS votos_candidatos (
    abr TEXT NOT NULL,
    numero TEXT NOT NULL,
    nome TEXT,
    nome_completo TEXT,
    partido TEXT,
    votos INTEGER,
    pct REAL,
    pct_str TEXT,
    seq INTEGER,
    eleito TEXT,
    situacao TEXT,
    PRIMARY KEY (abr, numero)
);

CREATE TABLE IF NOT EXISTS votos_secao (
    secao_id INTEGER PRIMARY KEY REFERENCES secoes(id),
    modelo_urna TEXT,
    uf TEXT,
    comparecimento INTEGER,
    votos_validos INTEGER,
    status TEXT,
    error TEXT,
    downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS votos_secao_cand (
    secao_id INTEGER NOT NULL REFERENCES secoes(id),
    numero TEXT NOT NULL,
    votos INTEGER NOT NULL,
    PRIMARY KEY (secao_id, numero)
);

CREATE INDEX IF NOT EXISTS idx_secoes_uf ON secoes(uf);
CREATE INDEX IF NOT EXISTS idx_arquivos_status_tipo ON arquivos(status, tipo);
CREATE INDEX IF NOT EXISTS idx_arquivos_secao ON arquivos(secao_id);
CREATE INDEX IF NOT EXISTS idx_votos_cand_abr ON votos_candidatos(abr);
CREATE INDEX IF NOT EXISTS idx_votos_secao_modelo ON votos_secao(modelo_urna);
CREATE INDEX IF NOT EXISTS idx_votos_secao_cand_num ON votos_secao_cand(numero);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=120)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        arq_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(arquivos)")}
        if "modelo_urna" not in arq_cols:
            self.conn.execute("ALTER TABLE arquivos ADD COLUMN modelo_urna TEXT")
        sec_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(secoes)")}
        if "modelo_urna" not in sec_cols:
            self.conn.execute("ALTER TABLE secoes ADD COLUMN modelo_urna TEXT")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arquivos_modelo ON arquivos(modelo_urna)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_secoes_modelo ON secoes(modelo_urna)"
        )
        # tabelas de votos (CREATE IF NOT EXISTS já no SCHEMA; reforço aqui)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS votos_abr (
                abr TEXT PRIMARY KEY,
                eleicao TEXT,
                cargo TEXT,
                turno TEXT,
                atualizado_em TEXT,
                secoes_totalizadas INTEGER,
                secoes_total INTEGER,
                secoes_totalizadas_pct TEXT,
                eleitorado_aptos INTEGER,
                votos_total INTEGER,
                votos_validos INTEGER,
                votos_brancos INTEGER,
                votos_nulos INTEGER,
                abstencoes INTEGER,
                raw_json TEXT,
                downloaded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS votos_candidatos (
                abr TEXT NOT NULL,
                numero TEXT NOT NULL,
                nome TEXT,
                nome_completo TEXT,
                partido TEXT,
                votos INTEGER,
                pct REAL,
                pct_str TEXT,
                seq INTEGER,
                eleito TEXT,
                situacao TEXT,
                PRIMARY KEY (abr, numero)
            );
            CREATE TABLE IF NOT EXISTS votos_secao (
                secao_id INTEGER PRIMARY KEY REFERENCES secoes(id),
                modelo_urna TEXT,
                uf TEXT,
                comparecimento INTEGER,
                votos_validos INTEGER,
                status TEXT,
                error TEXT,
                downloaded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS votos_secao_cand (
                secao_id INTEGER NOT NULL REFERENCES secoes(id),
                numero TEXT NOT NULL,
                votos INTEGER NOT NULL,
                PRIMARY KEY (secao_id, numero)
            );
            CREATE INDEX IF NOT EXISTS idx_votos_cand_abr ON votos_candidatos(abr);
            CREATE INDEX IF NOT EXISTS idx_votos_secao_modelo ON votos_secao(modelo_urna);
            CREATE INDEX IF NOT EXISTS idx_votos_secao_cand_num ON votos_secao_cand(numero);
            """
        )

    def close(self) -> None:
        self.conn.close()

    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def upsert_uf_config(
        self,
        uf: str,
        nome: Optional[str],
        cdp: Optional[str],
        dg: Optional[str],
        hg: Optional[str],
        n_secoes: int,
        http_status: int,
        raw_json: Optional[str],
        downloaded_at: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO uf_config(uf, nome, cdp, dg, hg, n_secoes, http_status, raw_json, downloaded_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(uf) DO UPDATE SET
                nome=excluded.nome,
                cdp=excluded.cdp,
                dg=excluded.dg,
                hg=excluded.hg,
                n_secoes=excluded.n_secoes,
                http_status=excluded.http_status,
                raw_json=excluded.raw_json,
                downloaded_at=excluded.downloaded_at
            """,
            (uf, nome, cdp, dg, hg, n_secoes, http_status, raw_json, downloaded_at),
        )

    def insert_secoes(self, rows: Iterable[tuple]) -> int:
        cur = self.conn.executemany(
            """
            INSERT OR IGNORE INTO secoes(
                uf, municipio_cd, municipio_nm, zona, secao, data_apuracao, hora_apuracao
            ) VALUES(?,?,?,?,?,?,?)
            """,
            list(rows),
        )
        return cur.rowcount if cur.rowcount is not None else 0

    def count(self, table: str, where: str = "1=1", params: tuple = ()) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params).fetchone()
        return int(row["c"])

    def pending_secoes_for_aux(
        self,
        ufs: Optional[list[str]] = None,
        limit: Optional[int] = None,
        refresh_after_seconds: float = 1800.0,
    ) -> list[sqlite3.Row]:
        """Seções que precisam de aux.json.

        Prioridade: nunca baixadas → falhas HTTP → refresh de aux ok sem log
        (só após cooldown). Sem o cooldown, UFs iniciais com aux ok mas log
        ainda ausente monopolizam cada lote e o progresso real trava.
        """
        sql = """
            SELECT s.*
            FROM secoes s
            LEFT JOIN aux a ON a.secao_id = s.id
            WHERE a.secao_id IS NULL
               OR IFNULL(a.http_status, 0) != 200
               OR (
                    NOT EXISTS (
                        SELECT 1 FROM arquivos ar
                        WHERE ar.secao_id = s.id AND ar.tipo = 'log'
                    )
                    AND (
                        ? <= 0
                        OR a.downloaded_at IS NULL
                        OR (julianday('now') - julianday(REPLACE(substr(a.downloaded_at, 1, 19), 'T', ' ')))
                            >= (? / 86400.0)
                    )
               )
        """
        params: list[Any] = [float(refresh_after_seconds), float(refresh_after_seconds)]
        if ufs:
            placeholders = ",".join("?" for _ in ufs)
            sql += f" AND s.uf IN ({placeholders})"
            params.extend(ufs)
        sql += """
            ORDER BY
                CASE
                    WHEN a.secao_id IS NULL THEN 0
                    WHEN IFNULL(a.http_status, 0) != 200 THEN 1
                    ELSE 2
                END,
                s.uf, s.municipio_cd, s.zona, s.secao
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.conn.execute(sql, params))

    def pending_logs(self, ufs: Optional[list[str]] = None, limit: Optional[int] = None) -> list[sqlite3.Row]:
        sql = """
            SELECT
                a.id AS arquivo_id,
                a.nome,
                a.tipo,
                a.status,
                c.hash,
                s.id AS secao_id,
                s.uf,
                s.municipio_cd,
                s.zona,
                s.secao
            FROM arquivos a
            JOIN cargas c ON c.id = a.carga_id
            JOIN secoes s ON s.id = a.secao_id
            WHERE a.tipo = 'log' AND a.status != 'ok'
        """
        params: list[Any] = []
        if ufs:
            placeholders = ",".join("?" for _ in ufs)
            sql += f" AND s.uf IN ({placeholders})"
            params.extend(ufs)
        sql += " ORDER BY s.uf, s.municipio_cd, s.zona, s.secao"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return list(self.conn.execute(sql, params))

    def upsert_aux(
        self,
        secao_id: int,
        http_status: int,
        st: Optional[str],
        raw_json: Optional[str],
        error: Optional[str],
        downloaded_at: str,
        hashes: list[dict[str, Any]],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO aux(secao_id, http_status, st, raw_json, error, downloaded_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(secao_id) DO UPDATE SET
                http_status=excluded.http_status,
                st=excluded.st,
                raw_json=excluded.raw_json,
                error=excluded.error,
                downloaded_at=excluded.downloaded_at
            """,
            (secao_id, http_status, st, raw_json, error, downloaded_at),
        )
        for h in hashes:
            self.conn.execute(
                """
                INSERT INTO cargas(secao_id, hash, st, dr, hr)
                VALUES(?,?,?,?,?)
                ON CONFLICT(secao_id, hash) DO UPDATE SET
                    st=excluded.st, dr=excluded.dr, hr=excluded.hr
                """,
                (secao_id, h["hash"], h.get("st"), h.get("dr"), h.get("hr")),
            )
            carga_id = self.conn.execute(
                "SELECT id FROM cargas WHERE secao_id=? AND hash=?",
                (secao_id, h["hash"]),
            ).fetchone()["id"]
            for arq in h.get("arq", []):
                self.conn.execute(
                    """
                    INSERT INTO arquivos(carga_id, secao_id, tipo, nome, status)
                    VALUES(?,?,?,?, 'pending')
                    ON CONFLICT(carga_id, tipo, nome) DO NOTHING
                    """,
                    (carga_id, secao_id, arq.get("tp"), arq.get("nm")),
                )

    def get_or_create_secao(
        self,
        uf: str,
        municipio_cd: str,
        zona: str,
        secao: str,
        municipio_nm: Optional[str] = None,
    ) -> int:
        uf = uf.lower()
        row = self.conn.execute(
            """
            SELECT id, municipio_nm FROM secoes
            WHERE uf=? AND municipio_cd=? AND zona=? AND secao=?
            """,
            (uf, municipio_cd, zona, secao),
        ).fetchone()
        if row:
            if municipio_nm and not (row["municipio_nm"] or "").strip():
                self.conn.execute(
                    "UPDATE secoes SET municipio_nm=? WHERE id=?",
                    (municipio_nm, row["id"]),
                )
            return int(row["id"])
        cur = self.conn.execute(
            """
            INSERT INTO secoes(uf, municipio_cd, municipio_nm, zona, secao)
            VALUES(?,?,?,?,?)
            """,
            (uf, municipio_cd, municipio_nm, zona, secao),
        )
        return int(cur.lastrowid)

    def import_bulk_log(
        self,
        *,
        uf: str,
        municipio_cd: str,
        zona: str,
        secao: str,
        nome: str,
        content: bytes,
        url: Optional[str] = None,
        store_blob: bool = True,
        extract_text: bool = False,
        downloaded_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Importa um .logjez/.jez já baixado (pacote em massa) para o SQLite."""
        from .downloader import extract_logd_dat
        from .modelo import parse_modelo_from_jez, parse_modelo_from_text

        digest = hashlib.sha256(content).hexdigest()
        secao_id = self.get_or_create_secao(uf, municipio_cd, zona, secao)
        self.conn.execute(
            """
            INSERT INTO cargas(secao_id, hash, st)
            VALUES(?,?,?)
            ON CONFLICT(secao_id, hash) DO UPDATE SET st=excluded.st
            """,
            (secao_id, digest, "bulk"),
        )
        carga_id = self.conn.execute(
            "SELECT id FROM cargas WHERE secao_id=? AND hash=?",
            (secao_id, digest),
        ).fetchone()["id"]
        self.conn.execute(
            """
            INSERT INTO arquivos(carga_id, secao_id, tipo, nome, status)
            VALUES(?,?, 'log', ?, 'pending')
            ON CONFLICT(carga_id, tipo, nome) DO NOTHING
            """,
            (carga_id, secao_id, nome),
        )
        arquivo_id = self.conn.execute(
            "SELECT id FROM arquivos WHERE carga_id=? AND tipo='log' AND nome=?",
            (carga_id, nome),
        ).fetchone()["id"]
        log_text = extract_logd_dat(content) if extract_text else None
        modelo = parse_modelo_from_text(log_text) if log_text else None
        if not modelo:
            modelo = parse_modelo_from_jez(content)
        modelo = modelo or "(não identificado)"
        self.mark_arquivo(
            arquivo_id,
            status="ok",
            url=url,
            size_bytes=len(content),
            sha256=digest,
            content=content if store_blob else None,
            log_text=log_text,
            modelo_urna=modelo,
            error=None,
            downloaded_at=downloaded_at,
        )
        return {
            "secao_id": secao_id,
            "arquivo_id": arquivo_id,
            "modelo_urna": modelo,
            "size_bytes": len(content),
        }

    def mark_arquivo(
        self,
        arquivo_id: int,
        *,
        status: str,
        url: Optional[str] = None,
        size_bytes: Optional[int] = None,
        sha256: Optional[str] = None,
        content: Optional[bytes] = None,
        log_text: Optional[str] = None,
        modelo_urna: Optional[str] = None,
        error: Optional[str] = None,
        downloaded_at: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE arquivos SET
                status=?,
                url=COALESCE(?, url),
                size_bytes=COALESCE(?, size_bytes),
                sha256=COALESCE(?, sha256),
                content=COALESCE(?, content),
                log_text=COALESCE(?, log_text),
                modelo_urna=COALESCE(?, modelo_urna),
                error=?,
                downloaded_at=COALESCE(?, downloaded_at)
            WHERE id=?
            """,
            (
                status,
                url,
                size_bytes,
                sha256,
                content,
                log_text,
                modelo_urna,
                error,
                downloaded_at,
                arquivo_id,
            ),
        )
        if modelo_urna:
            self.conn.execute(
                """
                UPDATE secoes
                SET modelo_urna = ?
                WHERE id = (SELECT secao_id FROM arquivos WHERE id = ?)
                """,
                (modelo_urna, arquivo_id),
            )

    def upsert_votos_presidente(
        self,
        parsed: dict[str, Any],
        raw_json: Optional[str],
        downloaded_at: str,
        cargo: str = "1",
    ) -> None:
        abr = parsed["abr"]
        self.conn.execute(
            """
            INSERT INTO votos_abr(
                abr, eleicao, cargo, turno, atualizado_em,
                secoes_totalizadas, secoes_total, secoes_totalizadas_pct,
                eleitorado_aptos, votos_total, votos_validos, votos_brancos,
                votos_nulos, abstencoes, raw_json, downloaded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(abr) DO UPDATE SET
                eleicao=excluded.eleicao,
                cargo=excluded.cargo,
                turno=excluded.turno,
                atualizado_em=excluded.atualizado_em,
                secoes_totalizadas=excluded.secoes_totalizadas,
                secoes_total=excluded.secoes_total,
                secoes_totalizadas_pct=excluded.secoes_totalizadas_pct,
                eleitorado_aptos=excluded.eleitorado_aptos,
                votos_total=excluded.votos_total,
                votos_validos=excluded.votos_validos,
                votos_brancos=excluded.votos_brancos,
                votos_nulos=excluded.votos_nulos,
                abstencoes=excluded.abstencoes,
                raw_json=excluded.raw_json,
                downloaded_at=excluded.downloaded_at
            """,
            (
                abr,
                parsed.get("eleicao"),
                cargo,
                parsed.get("turno"),
                parsed.get("atualizado_em"),
                parsed.get("secoes_totalizadas"),
                parsed.get("secoes_total"),
                parsed.get("secoes_totalizadas_pct"),
                parsed.get("eleitorado_aptos"),
                parsed.get("votos_total"),
                parsed.get("votos_validos"),
                parsed.get("votos_brancos"),
                parsed.get("votos_nulos"),
                parsed.get("abstencoes"),
                raw_json,
                downloaded_at,
            ),
        )
        self.conn.execute("DELETE FROM votos_candidatos WHERE abr=?", (abr,))
        self.conn.executemany(
            """
            INSERT INTO votos_candidatos(
                abr, numero, nome, nome_completo, partido, votos, pct, pct_str, seq, eleito, situacao
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    abr,
                    c["numero"],
                    c.get("nome"),
                    c.get("nome_completo"),
                    c.get("partido"),
                    c.get("votos"),
                    c.get("pct"),
                    c.get("pct_str"),
                    c.get("seq"),
                    c.get("eleito"),
                    c.get("situacao"),
                )
                for c in parsed.get("candidatos") or []
            ],
        )

    def set_modelo_arquivo(self, arquivo_id: int, modelo: Optional[str], secao_id: Optional[int] = None) -> None:
        self.conn.execute(
            "UPDATE arquivos SET modelo_urna=? WHERE id=?",
            (modelo, arquivo_id),
        )
        if secao_id is not None and modelo:
            self.conn.execute(
                "UPDATE secoes SET modelo_urna=? WHERE id=?",
                (modelo, secao_id),
            )
        elif modelo:
            self.conn.execute(
                """
                UPDATE secoes
                SET modelo_urna=?
                WHERE id=(SELECT secao_id FROM arquivos WHERE id=?)
                """,
                (modelo, arquivo_id),
            )

    def upsert_votos_secao(
        self,
        secao_id: int,
        *,
        modelo_urna: Optional[str],
        uf: str,
        votos: dict[str, int],
        status: str,
        error: Optional[str],
        downloaded_at: str,
    ) -> None:
        validos = sum(votos.values())
        self.conn.execute(
            """
            INSERT INTO votos_secao(secao_id, modelo_urna, uf, comparecimento, votos_validos, status, error, downloaded_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(secao_id) DO UPDATE SET
                modelo_urna=excluded.modelo_urna,
                uf=excluded.uf,
                comparecimento=excluded.comparecimento,
                votos_validos=excluded.votos_validos,
                status=excluded.status,
                error=excluded.error,
                downloaded_at=excluded.downloaded_at
            """,
            (secao_id, modelo_urna, uf, validos, validos, status, error, downloaded_at),
        )
        self.conn.execute("DELETE FROM votos_secao_cand WHERE secao_id=?", (secao_id,))
        if votos:
            self.conn.executemany(
                "INSERT INTO votos_secao_cand(secao_id, numero, votos) VALUES(?,?,?)",
                [(secao_id, num, qtd) for num, qtd in votos.items()],
            )

    def commit(self) -> None:
        self.conn.commit()

    def stats(self) -> dict[str, int]:
        return {
            "ufs": self.count("uf_config"),
            "secoes": self.count("secoes"),
            "aux_ok": self.count("aux", "http_status=200"),
            "aux_total": self.count("aux"),
            "cargas": self.count("cargas"),
            "logs_ok": self.count("arquivos", "tipo='log' AND status='ok'"),
            "logs_pending": self.count("arquivos", "tipo='log' AND status!='ok'"),
            "logs_total": self.count("arquivos", "tipo='log'"),
        }
