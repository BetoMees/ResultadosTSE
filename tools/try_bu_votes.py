"""Walker DER do BU para extrair votos do cargo Presidente."""

from __future__ import annotations

from pathlib import Path
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


def walk(data: bytes, i: int = 0, end: Optional[int] = None, unwrap_octets: bool = True) -> list[tuple[int, Any]]:
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
            out.append((tag, walk(chunk, unwrap_octets=unwrap_octets)))
        elif tag_num == 0x02:  # INTEGER
            out.append((tag, int.from_bytes(chunk, "big", signed=False) if chunk else 0))
        elif tag_num == 0x0A:  # ENUMERATED
            out.append((tag, int.from_bytes(chunk, "big", signed=False) if chunk else 0))
        elif tag_num == 0x04 and unwrap_octets and chunk[:1] == b"\x30":
            # OCTET STRING contendo SEQUENCE — desembrulha
            try:
                out.append((tag, walk(chunk, unwrap_octets=unwrap_octets)))
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
    tree = walk(bu)
    ints = flatten_ints(tree)
    votes: dict[str, int] = {}
    # Em TotalVotosVotavel nominal: codigo (NumeroVotavel) + quantidadeVotos
    # Procura cargo 1 e depois pares (cand, qtd) na sequência.
    for i, v in enumerate(ints):
        if v != 1:
            continue
        window = ints[i + 1 : i + 120]
        local: dict[str, int] = {}
        j = 0
        while j < len(window) - 1:
            a, b = window[j], window[j + 1]
            if a in candidate_numbers and 0 <= b <= 1500:
                local[str(a)] = b
                j += 2
                continue
            j += 1
        # só aceita janela se achou pelo menos 2 candidatos
        if len(local) >= 2:
            for k, q in local.items():
                votes[k] = votes.get(k, 0) + q
            # uma seção tem um bloco de presidente — para na primeira boa
            if sum(votes.values()) > 0:
                return votes
    # fallback: varredura global de pares cand/qtd mais frequentes
    if not votes:
        for j in range(len(ints) - 1):
            a, b = ints[j], ints[j + 1]
            if a in candidate_numbers and 0 <= b <= 1500:
                key = str(a)
                # guarda o maior (evita lixo pequeno de enums)
                if b >= votes.get(key, -1):
                    votes[key] = b
    return votes


def main() -> None:
    bu = Path(".cache/sample_bu.bin").read_bytes()
    cands = {22, 13, 55, 70, 14, 30, 80, 27, 21, 16, 35, 29}
    tree = walk(bu)
    ints = flatten_ints(tree)
    print("n_ints", len(ints))
    print("sample ints", ints[:100])
    print("votes", extract_presidente_votes(bu, cands))
    for c in sorted(cands):
        print(f"  count({c})={ints.count(c)}")


if __name__ == "__main__":
    main()
