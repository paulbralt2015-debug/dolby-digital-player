"""Source AC-3 avec accès par le temps : démarrage immédiat, déplacement (seek) possible."""
import threading, time, bisect
from . import demux


class Source:
    def __init__(self, path, track=0):
        self.path, self.track, self.kind = path, track, demux.detect(path)
        self.fs, self.t0, self.idx = 48000, 0.0, []
        self.pt, self.po, self.done = [], [], threading.Event()
        if self.kind in ("raw", "mp4", "mkv"):
            self.idx = demux.frame_index(path, self.kind, track); self.done.set()
            if not self.idx: raise ValueError("aucune piste AC-3 trouvée")
        else:
            first = next(((o, p) for o, p, _ in demux.chunks(path, self.kind, track) if p is not None), None)
            if first is None: raise ValueError("aucune piste AC-3 trouvée")
            self.t0 = first[1]
            threading.Thread(target=self._scan, daemon=True).start()
        frame, _ = next(self.frames_from(0.0)[0])
        self.fs = [48000, 44100, 32000][frame[4] >> 6]

    def _scan(self):
        last, wrap = None, 0.0
        for off, pts, _ in demux.chunks(self.path, self.kind, self.track):
            if pts is None: continue
            if last is not None and pts + wrap < last - 4e4: wrap += 2 ** 33 / 90000.0
            last = pts + wrap
            self.pt.append(last - self.t0); self.po.append(off)
        self.done.set()

    @property
    def duration(self):
        if self.idx: return len(self.idx) * 1536 / self.fs
        return (self.pt[-1] + 0.1) if (self.done.is_set() and self.pt) else None

    def frames_from(self, t):
        """-> (itérateur de (trame, pos), temps réel du début de la première trame)."""
        t = max(0.0, t)
        if self.idx:
            i = min(len(self.idx) - 1, int(t * self.fs / 1536))
            def gen():
                with open(self.path, "rb") as f:
                    for off, n in self.idx[i:]:
                        f.seek(off); yield f.read(n), off
            return gen(), i * 1536 / self.fs
        end = time.time() + 60
        while not self.done.is_set() and (not self.pt or self.pt[-1] < t + 1) and time.time() < end: time.sleep(0.02)
        k = max(0, bisect.bisect_right(self.pt, t) - 1) if self.pt else 0
        off, ts = (self.po[k], self.pt[k]) if self.pt else (0, 0.0)
        return demux.frames_from_chunks(demux.chunks(self.path, self.kind, self.track, off)), ts
