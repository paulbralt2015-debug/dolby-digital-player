"""Fichier -> trames AC-3 -> décodage -> effets -> WAV 16 bits."""
import os, struct
import numpy as np
from .decoder import AC3Decoder
from .demux import frames
from .effects import process
from .virtual import Virtualizer

def render(path, out, mode="loro", drc="dynrng", drc_cut=1.0, drc_boost=1.0, dialnorm=True,
           target=-27.0, track=0, progress=None):
    dec, total, n, fs, ch = AC3Decoder(drc, drc_cut, drc_boost), os.path.getsize(path), 0, 48000, 2
    virt = None
    with open(out, "wb") as w:
        w.write(b"\0" * 44)
        for data, pos in frames(path, track):
            try: pcm, meta = dec.decode(data)
            except Exception: continue            # trame corrompue : on saute
            if mode == "virtual":
                virt = virt or Virtualizer(meta.fs)
                y = virt.process(process(pcm, meta, "5.1", dialnorm, target))
            else: y = process(pcm, meta, mode, dialnorm, target)
            fs, ch = meta.fs, y.shape[1]
            w.write((y * 32767).astype("<i2").tobytes()); n += 1
            if progress and n % 50 == 0: progress(min(99, int(100 * pos / total)))
        size = w.tell() - 44
        w.seek(0)
        w.write(b"RIFF" + struct.pack("<I", min(size + 36, 0xFFFFFFFF)) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, ch, fs, fs * ch * 2, ch * 2, 16) +
                b"data" + struct.pack("<I", min(size, 0xFFFFFFFF)))
    if n == 0: raise RuntimeError("aucune piste Dolby Digital (AC-3) trouvée")
    return out
