"""Génère ac3/tables.py à partir du texte de la norme ATSC A/52:2018 (pdftotext -layout)."""
import re, sys
T = open(sys.argv[1], encoding="utf-8").read().split("\n")
def sect(start, stop):
    i = next(k for k, l in enumerate(T) if start in l and not re.search(r"\.{3,}|\s\d+$", l))
    j = next((k for k in range(i + 1, len(T)) if stop in T[k]), i + 60)
    return T[i + 1:j]
def small(title, nxt):
    return [int(m, 16) for l in sect(title, nxt) for m in re.findall(r"^\s*\d+\s+(0x[0-9a-f]+)\s*$", l)]
out = {}
out["SLOWDEC"] = small("Table 7.6 Slow Decay", "Table 7.7")
out["FASTDEC"] = small("Table 7.7 Fast Decay", "Table 7.8")
out["SLOWGAIN"] = small("Table 7.8 Slow Gain", "Table 7.9")
out["DBPBTAB"] = small("Table 7.9 dB/Bit", "Table 7.10")
out["FLOORTAB"] = [x - 65536 if x >= 32768 else x for x in small("Table 7.10 Floor", "Table 7.11")]  # 0xf800 = -2048 (signé 16 bits)
out["FASTGAIN"] = small("Table 7.11 Fast Gain", "Table 7.12")
bnd = {}
for l in sect("Table 7.12 Banding", "Table 7.13"):
    m = re.match(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", l)
    if m:
        a = list(map(int, m.groups())); bnd[a[0]] = (a[1], a[2]); bnd[a[3]] = (a[4], a[5])
out["BNDTAB"] = [bnd[i][0] for i in range(50)]
out["BNDSZ"] = [bnd[i][1] for i in range(50)]
mk = []
for l in sect("Table 7.13 Bin Number", "Table 7.14"):
    if re.match(r"^\s*A=\d+", l): mk += list(map(int, re.sub(r"^\s*A=\d+", "", l).split()))
out["MASKTAB"] = mk
out["LATAB"] = [int(x, 16) for l in sect("Table 7.14 Log-Addition", "Table 7.15") if re.match(r"^\s*A=", l) for x in re.findall(r"0x[0-9a-f]+", l)]
hth = {}
for l in sect("Table 7.15 Hearing", "Table 7.16"):
    m = re.match(r"^\s*(\d+)\s+(0x\w+)\s+(0x\w+)\s+(0x\w+)\s+(\d+)\s+(0x\w+)\s+(0x\w+)\s+(0x\w+)\s*$", l)
    if m:
        g = m.groups(); hth[int(g[0])] = [int(x, 16) for x in g[1:4]]; hth[int(g[4])] = [int(x, 16) for x in g[5:8]]
out["HTH"] = [[hth[b][f] for b in range(50)] for f in range(3)]
bap = {}
for l in sect("Table 7.16 Bit Allocation Pointer", "Table 7.17"):
    m = re.match(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", l)
    if m:
        a = list(map(int, m.groups())); bap[a[0]] = a[1]; bap[a[2]] = a[3]
out["BAPTAB"] = [bap[i] for i in range(64)]
out["WINDOW"] = [float(x) for l in sect("Table 7.33 Transform Window", "6) Overlap") if re.match(r"^\s*A=", l) for x in re.findall(r"\d\.\d{5}", l)]
fs = {}
for l in sect("Table 5.18 Frame Size Code", "Table 5.19"):
    m = re.match(r"^\s*.?(\d{6}).?\s*\(\d+\)\s+(\d+)\s*kbps\s+(\d+)\s+(\d+)\s+(\d+)", l)
    if m: fs[int(m.group(1), 2)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
out["FRMSIZE"] = [fs[i] for i in sorted(fs)]   # (kbps, mots@32k, mots@44.1k, mots@48k)
with open("ac3/tables.py", "w") as f:
    f.write("# Généré par tools_gen_tables.py depuis ATSC A/52:2018 — ne pas éditer à la main.\n")
    for k, v in out.items(): f.write(f"{k} = {v!r}\n")
print({k: (len(v) if not isinstance(v[0], list) else [len(x) for x in v]) for k, v in out.items()})
