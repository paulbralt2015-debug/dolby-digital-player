"""Tests : VOB/TS, lecture en continu et déplacement. FFmpeg sert UNIQUEMENT à fabriquer les fichiers de test."""
import sys, os, subprocess, time, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from ac3 import demux
from ac3.source import Source
from ac3.stream import Ac3Stream

def ff(a): subprocess.run(["ffmpeg", "-v", "error", "-y"] + a, check=True)
V = ["-f", "lavfi", "-i", "testsrc=d=6:s=160x120:r=25"]
files = {}
for name, fmt, ext in (("TS", "mpegts", "ts"), ("VOB", "vob", "vob")):
    p = f"/tmp/p.{ext}"
    ff(V + ["-i", "/tmp/s51.wav", "-c:v", "mpeg2video", "-c:a", "ac3", "-b:a", "448k", "-f", fmt, "-shortest", p])
    ff(["-i", p, "-vn", "-c:a", "copy", "-f", "ac3", "/tmp/ref_es.ac3"])
    exp = open("/tmp/ref_es.ac3", "rb").read(); got = b"".join(d for d, _ in demux.frames(p))
    print(f"{name}: {demux.detect(p)}  trames identiques à l'AC-3 d'ffmpeg: {got == exp} ({len(got)} / {len(exp)} octets)")
    files[name] = p
files["MKV"] = "/tmp/v.mkv"; files["MP4"] = "/tmp/v.mp4"
for name, p in files.items():
    t = time.time(); src = Source(p); s = Ac3Stream(src, mode="loro", dialnorm=False)
    first = s.read(44 + 48000 * 4); t_first = time.time() - t
    data = np.frombuffer(first[44:], "<i2").reshape(-1, 2).astype(float)
    # référence : décodage séquentiel complet
    s2 = Ac3Stream(src, mode="loro", dialnorm=False); full = b""
    while True:
        c = s2.read(1 << 18)
        if not c: break
        full += c
    ref = np.frombuffer(full[44:], "<i2").reshape(-1, 2).astype(float)
    T = 1.5; ofs = 44 + int(T * src.fs) * 4
    s.seek(ofs); part = np.frombuffer(s.read(48000 * 2), "<i2").reshape(-1, 2).astype(float)
    r = ref[int(T * src.fs):int(T * src.fs) + len(part)]; n = min(len(r), len(part))
    a, b = part[1024:n], r[1024:n]
    snr = 10 * np.log10(np.sum(b ** 2) / (np.sum((a - b) ** 2) + 1e-9))
    same = np.array_equal(data[:48000], ref[:48000])
    print(f"{name:8s} 1er audio après {t_first*1000:5.0f} ms | durée {src.duration and round(src.duration,2)} s fs={src.fs} t0={src.t0:.3f} | début identique: {same} | SNR après seek à 1,5 s: {snr:.1f} dB")
