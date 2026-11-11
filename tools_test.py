"""Compare ac3/decoder.py avec la sortie de FFmpeg (utilisé UNIQUEMENT pour les tests)."""
import subprocess, sys, numpy as np, os
sys.path.insert(0, os.path.dirname(__file__))
from ac3.decoder import AC3Decoder, frame_size

def ff(args): subprocess.run(["ffmpeg", "-v", "error", "-y"] + args, check=True)

def run(name, src_args, enc_args, nch):
    ff(src_args + ["-c:a", "ac3"] + enc_args + ["/tmp/t.ac3"])
    ff(["-i", "/tmp/t.ac3", "-f", "f32le", "-acodec", "pcm_f32le", "/tmp/ref.raw"])
    data = open("/tmp/t.ac3", "rb").read(); dec = AC3Decoder(); pos, out = 0, []
    while pos < len(data):
        n = frame_size(data, pos)
        if not n: break
        pcm, meta = dec.decode(data[pos:pos + n]); out.append(pcm); pos += n
    mine = np.concatenate(out)
    ref = np.fromfile("/tmp/ref.raw", np.float32).reshape(-1, nch)
    # colonnes FFmpeg 5.1 : FL FR FC LFE BL BR ; les miennes : L R C LFE Ls Rs
    cols = {2: [0, 1], 6: [0, 1, 2, 3, 4, 5]}[nch]
    n = min(len(mine), len(ref)) - 1536
    a, b = mine[:n][:, cols][1536:], ref[:n][:, :nch][1536:]
    for lag in (0,):
        err = a - b
        snr = 10 * np.log10(np.sum(b ** 2) / (np.sum(err ** 2) + 1e-20))
    f = np.fft.rfftfreq(len(a), 1 / 48000); A, B = np.abs(np.fft.rfft(a, axis=0)), np.abs(np.fft.rfft(b, axis=0))
    lo = f < 12000; snr_lo = 10 * np.log10(np.sum(B[lo] ** 2) / np.sum((np.abs(np.fft.rfft(a - b, axis=0))[lo]) ** 2))
    hi = ~lo; ratio = np.sqrt(np.sum(A[hi] ** 2) / np.sum(B[hi] ** 2))
    print(f"   -> SNR < 12 kHz = {snr_lo:.1f} dB ; énergie > 12 kHz mine/ref = {ratio:.3f}")
    print(f"{name}: acmod={meta.acmod} lfe={meta.lfeon} cpl={dec.s.cplinu} trames={len(out)} SNR={snr:.1f} dB  rms_mine={a.std():.4f} rms_ref={b.std():.4f}")

ff(["-f", "lavfi", "-i", "sine=f=440:d=3", "-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.3", "-filter_complex", "[0][1]amix=inputs=2,pan=stereo|c0=c0|c1=0.6*c0", "/tmp/st.wav"])
run("stéréo 192k", ["-i", "/tmp/st.wav"], ["-b:a", "192k"], 2)
run("stéréo 96k (matriçage)", ["-i", "/tmp/st.wav"], ["-b:a", "96k"], 2)
ff(["-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.2:s=1", "-f", "lavfi", "-i", "sine=f=330:d=3", "-f", "lavfi", "-i", "anoisesrc=d=3:c=brown:a=0.3:s=7",
    "-f", "lavfi", "-i", "sine=f=60:d=3", "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:a=0.05:s=3", "-f", "lavfi", "-i", "sine=f=1000:d=3",
    "-filter_complex", "[0][1][2][3][4][5]join=inputs=6:channel_layout=5.1", "/tmp/s51.wav"])
run("5.1 448k", ["-i", "/tmp/s51.wav"], ["-b:a", "448k"], 6)
