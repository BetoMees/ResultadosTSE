from pathlib import Path
from tools.try_bu_votes import walk

bu = Path(".cache/sample_bu.bin").read_bytes()
tree = walk(bu)


def count(node, d=None):
    d = d if d is not None else {"seq": 0, "int": 0, "enum": 0, "other": 0, "bytes": 0}
    if isinstance(node, list):
        for tag, val in node:
            if isinstance(val, list):
                d["seq"] += 1
                count(val, d)
            elif isinstance(val, int):
                if tag & 0x1F == 0x0A:
                    d["enum"] += 1
                else:
                    d["int"] += 1
            else:
                d["bytes"] += 1
                d["other"] += 1
    return d


print(count(tree))
print("top tags", [(hex(t), type(v).__name__, (len(v) if isinstance(v, (list, bytes)) else v)) for t, v in tree[:20]])
# show depth-2
for t, v in tree:
    if isinstance(v, list):
        print("child", hex(t), "n=", len(v), "sub", [(hex(a), type(b).__name__, (len(b) if isinstance(b,(list,bytes)) else b)) for a,b in v[:15]])
