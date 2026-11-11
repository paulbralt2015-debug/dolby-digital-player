"""Surround virtuel : 5.1 -> stéréo 3D (casque ou 2 enceintes), modèle binaural simplifié :
retard interaural (formule de Woodworth), ombre de la tête (passe-bas + atténuation) pour l'oreille
éloignée, ombre du pavillon pour l'arrière. Algorithme libre, pas celui de Dolby Virtual Speaker."""
import numpy as np

TAPS, LEN, D0 = 33, 81, 16
SPK = {0: +30, 1: -30, 2: 0, 4: +110, 5: -110}      # colonnes L,R,C,(LFE),Ls,Rs -> angle (+ = gauche)


def _lp(fc, fs):
    n = np.arange(TAPS) - (TAPS - 1) / 2
    h = np.sinc(2 * fc / fs * n) * np.hamming(TAPS)
    return h / h.sum()


def _filters(fs):
    """-> {colonne: (h_oreille_gauche, h_oreille_droite)}"""
    out = {}
    for ch, th in list(SPK.items()) + [(3, 0)]:
        a = abs(th); near, far = np.zeros(LEN), np.zeros(LEN)
        if ch == 2: near[D0] = far[D0] = 0.707
        elif ch == 3: near[D0] = far[D0] = 0.5
        else:
            rad = np.radians(a); d = int(round(0.0875 / 343 * (rad + np.sin(rad)) * fs))
            near[:TAPS] = _lp(7000, fs) if a > 90 else np.eye(1, TAPS, D0)[0]
            far[d:d + TAPS] = _lp(5000 - 3200 * a / 110, fs) * 10 ** (-(1.5 + 4.5 * a / 110) / 20)
        out[ch] = (near, far) if th >= 0 else (far, near)
    return out


class Virtualizer:
    def __init__(self, fs=48000, gain=0.65):
        self.f, self.g = _filters(fs), gain
        self.tail = {c: np.zeros(LEN - 1) for c in self.f}

    def process(self, x):
        """x (N, 6) [L,R,C,LFE,Ls,Rs] -> (N, 2)."""
        out = np.zeros((len(x), 2))
        for c, (hl, hr) in self.f.items():
            buf = np.concatenate([self.tail[c], x[:, c].astype(np.float64)])
            self.tail[c] = buf[-(LEN - 1):]
            out[:, 0] += np.convolve(buf, hl, "valid"); out[:, 1] += np.convolve(buf, hr, "valid")
        return np.clip(out * self.g, -1.0, 1.0)
