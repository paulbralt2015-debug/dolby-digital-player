"""Extraction des trames AC-3 : .ac3, MP4/MOV, MKV/WebM, MPEG-PS/VOB, MPEG-TS/M2TS (sans FFmpeg)."""
import os, struct
import numpy as np
from .decoder import frame_size

MASTER = {0x18538067, 0x1F43B675, 0xA0, 0x1654AE6B, 0xAE}


def detect(path):
    with open(path, "rb") as f: h = f.read(400)
    if h[:2] == b"\x0b\x77": return "raw"
    if h[:4] == b"\x1a\x45\xdf\xa3": return "mkv"
    if h[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"): return "mp4"
    if h[:4] == b"\x00\x00\x01\xba": return "ps"
    if len(h) > 376 and h[0] == 0x47 and h[188] == 0x47 and h[376] == 0x47: return "ts"
    if len(h) > 388 and h[4] == 0x47 and h[196] == 0x47 and h[388] == 0x47: return "m2ts"
    raise ValueError("format non pris en charge (.ac3, MP4/MOV, MKV, VOB/MPEG-PS, TS/M2TS)")


# ---------- conteneurs à trames indexables : raw, MP4, MKV ----------
def _raw_index(path):
    size, idx, pos = os.path.getsize(path), [], 0
    with open(path, "rb") as f:
        while pos + 5 <= size:
            f.seek(pos); n = frame_size(f.read(8), 0)
            if n is None: pos += 1; continue
            idx.append((pos, n)); pos += n
    return idx


def _mp4_index(path, track):
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        def boxes(a, b):
            while a + 8 <= b:
                f.seek(a); sz, t = struct.unpack(">I4s", f.read(8)); hdr = 8
                if sz == 1: sz = struct.unpack(">Q", f.read(8))[0]; hdr = 16
                elif sz == 0: sz = b - a
                yield t.decode("latin1"), a + hdr, a + sz; a += sz
        def find(a, b, name): return next(((x, y) for t, x, y in boxes(a, b) if t == name), None)
        found = []
        for t, a, b in boxes(*find(0, size, "moov")):
            if t != "trak": continue
            stbl = find(*find(*find(a, b, "mdia"), "minf"), "stbl")
            f.seek(find(*stbl, "stsd")[0] + 12)
            if f.read(4) != b"ac-3": continue
            f.seek(find(*stbl, "stsz")[0] + 4); fixed, n = struct.unpack(">II", f.read(8))
            sizes = [fixed] * n if fixed else list(struct.unpack(f">{n}I", f.read(4 * n)))
            f.seek(find(*stbl, "stsc")[0] + 4); n = struct.unpack(">I", f.read(4))[0]
            stsc = [struct.unpack(">III", f.read(12)) for _ in range(n)]
            c = find(*stbl, "stco"); wide = c is None
            if wide: c = find(*stbl, "co64")
            f.seek(c[0] + 4); n = struct.unpack(">I", f.read(4))[0]
            offs = struct.unpack(">" + ("Q" if wide else "I") * n, f.read(n * (8 if wide else 4)))
            found.append((sizes, stsc, offs))
        if track >= len(found): return []
        sizes, stsc, offs = found[track]; idx, si = [], 0
        for ci, off in enumerate(offs):
            per = [s for s in stsc if s[0] <= ci + 1][-1][1]
            for _ in range(per):
                if si >= len(sizes): return idx
                idx.append((off, sizes[si])); off += sizes[si]; si += 1
        return idx


def _mkv_index(path, track):
    tracks, cur, idx = [], {}, []
    with open(path, "rb") as f:
        def vint(keep):
            b = f.read(1)
            if not b: return None, 0
            n, m = 1, 0x80
            while n <= 8 and not (b[0] & m): n += 1; m >>= 1
            v = b[0] if keep else b[0] & (m - 1)
            for x in f.read(n - 1): v = (v << 8) | x
            return v, n
        def walk(end):
            while f.tell() < end:
                eid, _ = vint(True)
                if eid is None: return
                sz, n = vint(False); unk = sz == (1 << (7 * n)) - 1
                start = f.tell(); stop = end if unk else start + sz
                if eid in MASTER:
                    if eid == 0xAE: cur.clear()
                    walk(stop)
                    if eid == 0xAE and cur.get("codec") == "A_AC3": tracks.append(cur.get("num"))
                elif eid == 0xD7: cur["num"] = int.from_bytes(f.read(sz), "big")
                elif eid == 0x86: cur["codec"] = f.read(sz).decode("latin1").strip("\0")
                elif eid in (0xA3, 0xA1):
                    tn, k = vint(False)
                    if track < len(tracks) and tn == tracks[track]:
                        f.read(3); idx.append((f.tell(), sz - k - 3))
                if not unk: f.seek(stop)
        walk(os.fstat(f.fileno()).st_size)
    return idx


def frame_index(path, kind, track=0):
    return {"raw": lambda: _raw_index(path), "mp4": lambda: _mp4_index(path, track),
            "mkv": lambda: _mkv_index(path, track)}[kind]()


# ---------- MPEG-PS (VOB) et MPEG-TS : flux d'octets reconstitué + PTS ----------
def _pts(b): return (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)


def _pes(b):
    """b commence à 00 00 01 sid ; -> (pts en secondes ou None, taille d'en-tête)."""
    if len(b) < 9: return None, len(b)
    return (_pts(b[9:14]) / 90000.0 if (b[7] & 0x80 and len(b) >= 14) else None), 9 + b[8]


def _ps_chunks(f, track, start=0):
    f.seek(start); buf, base, i = b"", start, 0
    while True:
        j = buf.find(b"\x00\x00\x01", i)
        if j < 0 or j + 14 > len(buf):
            chunk = f.read(1 << 20)
            if not chunk: return
            cut = j if j >= 0 else max(i, len(buf) - 2)
            base += cut; buf = buf[cut:] + chunk; i = 0; continue
        sid = buf[j + 3]
        if sid == 0xBA: i = j + ((14 + (buf[j + 13] & 7)) if buf[j + 4] >> 6 == 1 else 12); continue
        if sid < 0xB9: i = j + 3; continue
        ln = (buf[j + 4] << 8) | buf[j + 5]
        if j + 6 + ln > len(buf):
            chunk = f.read(1 << 20)
            if not chunk: return
            base += j; buf = buf[j:] + chunk; i = 0; continue
        if sid == 0xBD:
            pkt = buf[j:j + 6 + ln]; pts, hs = _pes(pkt); pl = pkt[hs:]
            if pl and pl[0] == 0x80 + track: yield base + j, pts, pl[4:]
        i = j + 6 + ln


def _ts_layout(path, kind): return (192, 4) if kind == "m2ts" else (188, 0)


def _ts_audio_pid(path, kind, track):
    psz, hdr = _ts_layout(path, kind); pmts, found = set(), []
    with open(path, "rb") as f:
        for _ in range(60000):
            p = f.read(psz)
            if len(p) < psz: break
            p = p[hdr:]
            if p[0] != 0x47 or not (p[1] & 0x40): continue
            pid = ((p[1] & 0x1F) << 8) | p[2]; o = 4 + ((1 + p[4]) if p[3] & 0x20 else 0)
            t = p[o + 1 + p[o]:]
            if pid == 0 and t[0] == 0:
                for k in range(8, 3 + ((t[1] & 15) << 8 | t[2]) - 4, 4):
                    if (t[k] << 8 | t[k + 1]) != 0: pmts.add(((t[k + 2] & 0x1F) << 8) | t[k + 3])
            elif pid in pmts and t[0] == 2:
                end = 3 + ((t[1] & 15) << 8 | t[2]) - 4; k = 12 + ((t[10] & 15) << 8 | t[11]); found = []
                while k + 5 <= end:
                    st, epid, il = t[k], ((t[k + 1] & 0x1F) << 8) | t[k + 2], ((t[k + 3] & 15) << 8) | t[k + 4]
                    d = t[k + 5:k + 5 + il]; tags, q = set(), 0
                    while q + 2 <= len(d): tags.add(d[q]); q += 2 + d[q + 1]
                    if st == 0x81 or (st == 0x06 and 0x6A in tags): found.append(epid)
                    k += 5 + il
                if track < len(found): return found[track]
    raise ValueError("aucune piste AC-3 trouvée dans le flux de transport")


def _ts_chunks(f, pid, psz, hdr, start=0):
    off = start - start % psz
    while True:
        f.seek(off); data = f.read(psz * 4000)
        n = len(data) // psz
        if n == 0: return
        a = np.frombuffer(data, np.uint8, count=n * psz).reshape(n, psz)[:, hdr:hdr + 188]
        pids = ((a[:, 1].astype(np.uint16) & 0x1F) << 8) | a[:, 2]
        for r in np.nonzero(pids == pid)[0]:
            p = a[r]; afc = (int(p[3]) >> 4) & 3
            if not afc & 1: continue
            o = 5 + int(p[4]) if afc & 2 else 4
            pay = p[o:188].tobytes(); pts = None
            if p[1] & 0x40 and pay[:3] == b"\x00\x00\x01":
                pts, hs = _pes(pay); pay = pay[hs:]
            yield off + int(r) * psz, pts, pay
        off += n * psz


def chunks(path, kind, track=0, start=0, _pid=[None]):
    """Génère (offset, pts_ou_None, octets) des paquets PES audio AC-3."""
    with open(path, "rb") as f:
        if kind == "ps": yield from _ps_chunks(f, track, start)
        else:
            psz, hdr = _ts_layout(path, kind)
            yield from _ts_chunks(f, _ts_audio_pid(path, kind, track), psz, hdr, start)


def frames_from_chunks(it):
    buf, pos = bytearray(), 0
    for off, _, c in it:
        buf += c; pos = off
        while True:
            i = buf.find(b"\x0b\x77")
            if i < 0: del buf[:-1]; break
            if i: del buf[:i]
            n = frame_size(buf, 0)
            if n is None: del buf[:2]; continue
            if len(buf) < n + 2: break
            if buf[n:n + 2] != b"\x0b\x77": del buf[:2]; continue
            yield bytes(buf[:n]), pos; del buf[:n]
    n = frame_size(buf, 0) if len(buf) > 5 else None
    if n and len(buf) >= n: yield bytes(buf[:n]), pos


def frames(path, track=0):
    """Génère (trame_ac3, position_dans_le_fichier) pour tous les formats pris en charge."""
    kind = detect(path)
    if kind in ("ps", "ts", "m2ts"):
        yield from frames_from_chunks(chunks(path, kind, track)); return
    with open(path, "rb") as f:
        for off, n in frame_index(path, kind, track):
            f.seek(off); yield f.read(n), off
