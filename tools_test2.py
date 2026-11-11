import sys, os, subprocess, numpy as np, wave
sys.path.insert(0, os.path.dirname(__file__))
from ac3 import demux, pipeline
def ff(a): subprocess.run(["ffmpeg", "-v", "error", "-y"] + a, check=True)
ff(["-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=25", "-i", "/tmp/s51.wav", "-c:v", "mpeg4", "-c:a", "ac3", "-b:a", "448k", "-shortest", "/tmp/v.mp4"])
ff(["-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=25", "-i", "/tmp/s51.wav", "-c:v", "mpeg4", "-c:a", "ac3", "-b:a", "448k", "-shortest", "/tmp/v.mkv"])
raw = open("/tmp/t.ac3", "rb").read()
ref = [raw[p:p + 1] for p in []]
for p in ("/tmp/v.mp4", "/tmp/v.mkv"):
    fr = [d for d, _ in demux.frames(p)]
    ff(["-i", p, "-vn", "-c:a", "copy", "-f", "ac3", "/tmp/x.ac3"])
    exp = open("/tmp/x.ac3", "rb").read()
    print(os.path.basename(p), "trames:", len(fr), "identique à l'AC-3 extrait par ffmpeg:", b"".join(fr) == exp)
for mode in ("5.1", "loro", "ltrt", "mono"):
    pipeline.render("/tmp/v.mkv", f"/tmp/o_{mode}.wav", mode=mode)
    w = wave.open(f"/tmp/o_{mode}.wav"); a = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())
    print(mode, "canaux", w.getnchannels(), "durée", round(w.getnframes() / w.getframerate(), 2), "s  crête", int(abs(a).max()), "rms/canal", [int(x) for x in a.std(0)])
