"""Effets Dolby Digital pilotés par les métadonnées : mixage, dialnorm."""
import numpy as np

CMIX = [0.707, 0.595, 0.500, 0.595]   # cmixlev (code 3 = réservé)
SMIX = [0.707, 0.500, 0.0, 0.500]     # surmixlev (code 3 = réservé)


def process(pcm, meta, mode="loro", dialnorm=True, target=-27.0, lfe_mix=0.0):
    """pcm (N, 6) [L,R,C,LFE,Ls,Rs] -> (N, c). mode : '5.1', 'loro', 'ltrt', 'mono'."""
    a = meta.acmod
    L, R, C, LFE, Ls, Rs = pcm.T.astype(np.float64)
    if dialnorm: g = 10 ** ((meta.dialnorm + target) / 20.0)
    else: g = 1.0
    if mode == "5.1":
        out = pcm.astype(np.float64)
    else:
        has_c, has_s, single = a in (3, 5, 7), a >= 4, a in (4, 5)
        cm, sm = CMIX[meta.cmixlev], SMIX[meta.surmixlev]
        if a == 1: Lo = Ro = C * 0.707
        elif a == 0: Lo, Ro = L, R
        elif mode == "ltrt":
            k = 0.707
            sl = Ls * k if single else (Ls + Rs) * k
            Lo = L + k * C * has_c - sl * has_s
            Ro = R + k * C * has_c + sl * has_s
            norm = 1 + k * has_c + k * has_s
            Lo, Ro = Lo / norm, Ro / norm
        else:
            s_l = Ls * (0.707 if single else 1.0); s_r = (Ls if single else Rs) * (0.707 if single else 1.0)
            Lo = L + cm * C * has_c + sm * s_l * has_s
            Ro = R + cm * C * has_c + sm * s_r * has_s
            norm = 1 + cm * has_c + sm * has_s * (0.707 if single else 1.0)
            Lo, Ro = Lo / norm, Ro / norm
        if lfe_mix: Lo, Ro = Lo + lfe_mix * LFE, Ro + lfe_mix * LFE
        out = np.stack([(Lo + Ro) / 2] if mode == "mono" else [Lo, Ro], 1)
    return np.clip(out * g, -1.0, 1.0)
