"""Parser heurístico do BU (ASN.1 DER) para votos de Presidente."""

from __future__ import annotations

from typing import Any, Optional


def _read_len(data: bytes, i: int) -> tuple[int, int]:
    first = data[i]
    i += 1
    if first < 0x80:
        return first, i
    n = first & 0x7F
    if n == 0 or i + n > len(data):
        raise ValueError("bad length")
    val = int.from_bytes(data[i : i + n], "big")
    return val, i + n


def walk(data: bytes, i: int = 0, end: Optional[int] = None) -> list[tuple[int, Any]]:
    end = len(data) if end is None else end
    out: list[tuple[int, Any]] = []
    while i < end:
        if i >= len(data):
            break
        tag = data[i]
        i += 1
        try:
            length, i = _read_len(data, i)
        except ValueError:
            break
        if i + length > len(data):
            break
        chunk = data[i : i + length]
        i += length
        constructed = bool(tag & 0x20)
        tag_num = tag & 0x1F
        if constructed:
            out.append((tag, walk(chunk)))
        elif tag_num == 0x02:
            out.append((tag, int.from_bytes(chunk, "big", signed=False) if chunk else 0))
        elif tag_num == 0x0A:
            out.append((tag, int.from_bytes(chunk, "big", signed=False) if chunk else 0))
        elif tag_num == 0x04 and chunk[:1] == b"\x30":
            try:
                out.append((tag, walk(chunk)))
            except Exception:
                out.append((tag, chunk))
        else:
            out.append((tag, chunk))
    return out


def flatten_ints(node: Any, acc: list[int] | None = None) -> list[int]:
    acc = acc if acc is not None else []
    if isinstance(node, int):
        acc.append(node)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, tuple) and len(item) == 2:
                flatten_ints(item[1], acc)
            else:
                flatten_ints(item, acc)
    return acc


def extract_presidente_votes(bu: bytes, candidate_numbers: set[int]) -> dict[str, int]:
    """
    Padrão no BU 2026 para votável nominal:
    quantidadeVotos, codigo, codigo, ordemGeracaoHash
    Escolhe o conjunto com ordens 1..N consecutivas e maior soma de votos.
    """
    ints = flatten_ints(walk(bu))
    start = 0
    for i, v in enumerate(ints):
        if v == 6257:
            start = i
            break
    window = ints[start : start + 250]
    hits: list[tuple[int, int, int]] = []  # ordem, cand, qtd
    for j in range(len(window) - 3):
        q, a, b, ordem = window[j], window[j + 1], window[j + 2], window[j + 3]
        if a == b and a in candidate_numbers and q != a and 0 <= q <= 2000 and 1 <= ordem <= 30:
            hits.append((ordem, a, q))
    if not hits:
        return {}
    # agrupa por "faixa" de ordens começando em 1
    by_ordem: dict[int, tuple[int, int]] = {}
    for ordem, cand, q in hits:
        # preferir maior qtd para a mesma ordem
        prev = by_ordem.get(ordem)
        if prev is None or q > prev[1]:
            by_ordem[ordem] = (cand, q)
    # pega sequência 1..k
    votes: dict[str, int] = {}
    k = 1
    while k in by_ordem:
        cand, q = by_ordem[k]
        votes[str(cand)] = q
        k += 1
    return votes
