"""Flux WAV virtuel décodé à la demande (lecture en continu, seekable), pour un protocole de flux libmpv."""
import struct, threading
import numpy as np
from .decoder import AC3Decoder
from .effects import process
from .virtual import Virtualizer


def wav_header(ch, fs, size):
    return (b"RIFF" + struct.pack("<I", min(size + 36, 0xFFFFFFFF)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, ch, fs, fs * ch * 2, ch * 2, 16) + b"data" + struct.pack("<I", min(size, 0xFFFFFFFF)))


class Ac3Stream:
    """Objet attendu par python-mpv (register_stream_protocol) : read / seek / close / size."""
    def __init__(self, src, mode="loro", drc="dynrng", drc_cut=1.0, drc_boost=1.0, dialnorm=True,
                 target=-27.0, duration_hint=None):
        self.src, self.mode, self.dn, self.target = src, mode, dialnorm, target
        self.drc = (drc, drc_cut, drc_boost)
        self.ch, self.fs = {"5.1": 6, "mono": 1}.get(mode, 2), src.fs  # "virtual" = stéréo
        dur = src.duration or duration_hint or 4 * 3600
        self.size = 44 + (int(dur * self.fs) + 1536) * self.ch * 2
        self.header, self.lock = wav_header(self.ch, self.fs, self.size - 44), threading.Lock()
        self._start(0.0); self.pos = 0

    def _start(self, t):
        self.dec = AC3Decoder(*self.drc)
        self.virt = Virtualizer(self.fs) if self.mode == "virtual" else None
        self.it, ts = self.src.frames_from(t)
        self.buf = bytearray()
        self.skip = int(round((t - ts) * self.fs)) if t >= ts else 0
        if t < ts: self.buf += bytes(int(round((ts - t) * self.fs)) * self.ch * 2)

    def _more(self):
        got = False
        for _ in range(4):
            fr = next(self.it, None)
            if fr is None: break
            try: pcm, meta = self.dec.decode(fr[0])
            except Exception: continue
            if self.virt is not None: y = self.virt.process(process(pcm, meta, "5.1", self.dn, self.target))
            else: y = process(pcm, meta, self.mode, self.dn, self.target)
            y = (y * 32767).astype("<i2")
            if self.skip:
                d = min(self.skip, len(y)); y = y[d:]; self.skip -= d
            self.buf += y.tobytes(); got = True
        return got

    def read(self, n):
        with self.lock:
            out = bytearray()
            while len(out) < n:
                if self.pos < 44: take = self.header[self.pos:self.pos + n - len(out)]
                elif self.buf: take = bytes(self.buf[:n - len(out)]); del self.buf[:len(take)]
                elif not self._more(): break
                else: continue
                out += take; self.pos += len(take)
            return bytes(out)

    def seek(self, off):
        with self.lock:
            off = max(0, min(int(off), self.size))
            if off < 44: self.pos = off; return off
            s = (off - 44) // (self.ch * 2); self.pos = 44 + s * self.ch * 2
            self._start(s / self.fs); return self.pos

    def close(self): pass
