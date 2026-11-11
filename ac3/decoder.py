"""Décodeur Dolby Digital (AC-3) écrit d'après ATSC A/52:2018. Aucune dépendance à FFmpeg."""
import zlib
import numpy as np
from types import SimpleNamespace as NS
from .tables import (SLOWDEC, FASTDEC, SLOWGAIN, DBPBTAB, FLOORTAB, FASTGAIN, BNDTAB, BNDSZ,
                     MASKTAB, LATAB, HTH, BAPTAB, WINDOW, FRMSIZE)

NFCHANS = [2, 1, 2, 3, 3, 4, 4, 5]
QNTZ = {6: 5, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10, 12: 11, 13: 12, 14: 14, 15: 16}
Q3 = [-2 / 3, 0, 2 / 3]
Q5 = [-4 / 5, -2 / 5, 0, 2 / 5, 4 / 5]
Q7 = [(2 * i - 6) / 7 for i in range(7)]
Q11 = [(2 * i - 10) / 11 for i in range(11)]
Q15 = [(2 * i - 14) / 15 for i in range(15)]
W = np.array(WINDOW)
_k = np.arange(128); _k2 = np.arange(64)
XC1 = -np.cos(2 * np.pi * (8 * _k + 1) / 4096); XS1 = -np.sin(2 * np.pi * (8 * _k + 1) / 4096)
XC2 = -np.cos(2 * np.pi * (8 * _k2 + 1) / 2048); XS2 = -np.sin(2 * np.pi * (8 * _k2 + 1) / 2048)


class BitReader:
    def __init__(self, data):
        self.v = int.from_bytes(data, "big"); self.n = len(data) * 8; self.p = 0
    def read(self, n):
        self.p += n
        return (self.v >> (self.n - self.p)) & ((1 << n) - 1) if n else 0


def frame_size(data, pos=0):
    """Taille en octets de la trame commençant à data[pos] (ou None si en-tête invalide)."""
    if data[pos:pos + 2] != b"\x0b\x77" or len(data) < pos + 5: return None
    fs, fr = data[pos + 4] >> 6, data[pos + 4] & 63
    if fs == 3 or fr > 37: return None
    return FRMSIZE[fr][{0: 3, 1: 2, 2: 1}[fs]] * 2


def decode_exps(absexp, groups, grpsize):
    d = []
    for g in groups: d += [g // 25 - 2, (g % 25) // 5 - 2, g % 5 - 2]
    e, prev = [absexp], absexp
    for x in d:
        prev += x; e += [prev] * grpsize
    return e


def logadd(a, b):
    c = a - b; a_ = LATAB[min(abs(c) >> 1, 255)]
    return a + a_ if c >= 0 else b + a_


def calc_lowcomp(a, b0, b1, b):
    if b < 7:
        if b0 + 256 == b1: a = 384
        elif b0 > b1: a = max(0, a - 64)
    elif b < 20:
        if b0 + 256 == b1: a = 320
        elif b0 > b1: a = max(0, a - 64)
    else: a = max(0, a - 128)
    return a


def calc_bap(exp, start, end, fscod, p, fgaincod, snroff, dba, leak=None):
    sdecay, fdecay = SLOWDEC[p.sdcycod], FASTDEC[p.fdcycod]
    sgain, dbknee, floor = SLOWGAIN[p.sgaincod], DBPBTAB[p.dbpbcod], FLOORTAB[p.floorcod]
    fgain = FASTGAIN[fgaincod]
    psd = [0] * 256
    for b in range(start, end): psd[b] = 3072 - (exp[b] << 7)
    bndpsd = [0] * 51
    j, k = start, MASKTAB[start]
    while True:
        last = min(BNDTAB[k] + BNDSZ[k], end)
        bndpsd[k] = psd[j]; j += 1
        while j < last:
            bndpsd[k] = logadd(bndpsd[k], psd[j]); j += 1
        k += 1
        if end <= last: break
    bs, be = MASKTAB[start], MASKTAB[end - 1] + 1
    ex = [0] * 51
    if bs == 0:
        lc = calc_lowcomp(0, bndpsd[0], bndpsd[1], 0); ex[0] = bndpsd[0] - fgain - lc
        lc = calc_lowcomp(lc, bndpsd[1], bndpsd[2], 1); ex[1] = bndpsd[1] - fgain - lc
        begin = 7
        for b in range(2, 7):
            if be != 7 or b != 6: lc = calc_lowcomp(lc, bndpsd[b], bndpsd[b + 1], b)
            fl, sl = bndpsd[b] - fgain, bndpsd[b] - sgain
            ex[b] = fl - lc
            if (be != 7 or b != 6) and bndpsd[b] <= bndpsd[b + 1]:
                begin = b + 1; break
        for b in range(begin, min(be, 22)):
            if be != 7 or b != 6: lc = calc_lowcomp(lc, bndpsd[b], bndpsd[b + 1], b)
            fl = max(fl - fdecay, bndpsd[b] - fgain); sl = max(sl - sdecay, bndpsd[b] - sgain)
            ex[b] = max(fl - lc, sl)
        begin = 22
    else:
        begin = bs; fl, sl = leak
    for b in range(begin, be):
        fl = max(fl - fdecay, bndpsd[b] - fgain); sl = max(sl - sdecay, bndpsd[b] - sgain)
        ex[b] = max(fl, sl)
    mask = [0] * 51
    for b in range(bs, be):
        if bndpsd[b] < dbknee: ex[b] += (dbknee - bndpsd[b]) >> 2
        mask[b] = max(ex[b], HTH[fscod][b])
    if dba:
        band = 0
        for off, ln, ba in dba:
            band += off
            delta = ((ba - 3) << 7) if ba >= 4 else ((ba - 4) << 7)
            for _ in range(ln):
                if band < 50: mask[band] += delta
                band += 1
    bap = [0] * 256
    i, j = start, MASKTAB[start]
    while True:
        last = min(BNDTAB[j] + BNDSZ[j], end)
        m = max(0, mask[j] - snroff - floor) & 0x1fe0
        m += floor
        for _ in range(i, last):
            bap[i] = BAPTAB[min(63, max(0, (psd[i] - m) >> 5))]; i += 1
        j += 1
        if end <= last: break
    return bap


def imdct(X, short, delay):
    """X : 256 coefficients -> 256 échantillons PCM (recouvrement-addition inclus)."""
    x = np.zeros(512); n = np.arange(64)
    if not short:
        Z = (X[255 - 2 * _k] * XC1 - X[2 * _k] * XS1) + 1j * (X[2 * _k] * XC1 + X[255 - 2 * _k] * XS1)
        y = np.fft.ifft(Z) * 128 * (XC1 + 1j * XS1); yr, yi = y.real, y.imag
        x[2 * n] = -yi[64 + n] * W[2 * n]; x[2 * n + 1] = yr[63 - n] * W[2 * n + 1]
        x[128 + 2 * n] = -yr[n] * W[128 + 2 * n]; x[129 + 2 * n] = yi[127 - n] * W[129 + 2 * n]
        x[256 + 2 * n] = -yr[64 + n] * W[255 - 2 * n]; x[257 + 2 * n] = yi[63 - n] * W[254 - 2 * n]
        x[384 + 2 * n] = yi[n] * W[127 - 2 * n]; x[385 + 2 * n] = -yr[127 - n] * W[126 - 2 * n]
    else:
        ys = []
        for X1 in (X[0::2], X[1::2]):
            Z = (X1[127 - 2 * _k2] * XC2 - X1[2 * _k2] * XS2) + 1j * (X1[2 * _k2] * XC2 + X1[127 - 2 * _k2] * XS2)
            ys.append(np.fft.ifft(Z) * 64 * (XC2 + 1j * XS2))
        (yr1, yi1), (yr2, yi2) = [(y.real, y.imag) for y in ys]
        x[2 * n] = -yi1[n] * W[2 * n]; x[2 * n + 1] = yr1[63 - n] * W[2 * n + 1]
        x[128 + 2 * n] = -yr1[n] * W[128 + 2 * n]; x[129 + 2 * n] = yi1[63 - n] * W[129 + 2 * n]
        x[256 + 2 * n] = -yr2[n] * W[255 - 2 * n]; x[257 + 2 * n] = yi2[63 - n] * W[254 - 2 * n]
        x[384 + 2 * n] = yi2[n] * W[127 - 2 * n]; x[385 + 2 * n] = -yr2[63 - n] * W[126 - 2 * n]
    return 2 * (x[:256] + delay), x[256:].copy()


def dyn_gain(word, bits):
    """Gain linéaire d'un mot dynrng (bits=3) ou compr (bits=4) : 2^(X+1) * (0,5 .. <1)."""
    low = 8 - bits; X = word >> low
    if X >= 1 << (bits - 1): X -= 1 << bits
    return 2.0 ** (X + 1) * ((1 << low) + (word & ((1 << low) - 1))) / (1 << (low + 1))


P2 = [2.0 ** -i for i in range(64)]
# colonnes de sortie : L, R, C, LFE, Ls, Rs
OUTMAP = {0: [[0], [1]], 1: [[2]], 2: [[0], [1]], 3: [[0], [2], [1]], 4: [[0], [1], [4, 5]],
          5: [[0], [2], [1], [4, 5]], 6: [[0], [1], [4], [5]], 7: [[0], [2], [1], [4], [5]]}


class AC3Decoder:
    """decode(trame) -> (pcm (1536, 6) float32 [L,R,C,LFE,Ls,Rs], meta).
    drc : 'dynrng' (défaut de la norme), 'compr' (compression forte) ou 'none'.
    drc_cut / drc_boost : fraction (0..1) appliquée aux réductions / aux amplifications."""
    def __init__(self, drc="dynrng", drc_cut=1.0, drc_boost=1.0):
        self.drc, self.cut, self.boost = drc, drc_cut, drc_boost
        self.s = NS(cplinu=0, chincpl=[0] * 5, phsflginu=0, cplbegf=0, cplendf=0, bstrc=[0], nbnd=1,
                    cplco=np.zeros((5, 18)), phsflg=[0] * 18, remat=[0] * 4, bwcod=[0] * 5,
                    exp=[[0] * 256 for _ in range(6)], cplexp=[0] * 256, dba=[None] * 6,
                    p=NS(sdcycod=0, fdcycod=0, sgaincod=0, dbpbcod=0, floorcod=0),
                    csnr=0, fsnr=[0] * 5, fgain=[0] * 5, cplfsnr=0, cplfgain=0, lfefsnr=0, lfefgain=0,
                    cplfleak=0, cplsleak=0, dynrng=0, dynrng2=0, seed=1)
        self.delay = np.zeros((6, 256))
        self.rng = np.random.default_rng(1)

    def decode(self, data):
        r = BitReader(data)
        seed = zlib.crc32(data)  # bruit de remplissage reproductible (identique après un déplacement)
        self.rng = np.random.default_rng(seed); self.s.seed = (seed & 0x7FFFFFFF) or 1
        if r.read(16) != 0x0B77: raise ValueError("pas de mot de synchronisation")
        r.read(16); fscod = r.read(2); r.read(6)
        bsid = r.read(5); bsmod = r.read(3); acmod = r.read(3)
        m = NS(acmod=acmod, bsid=bsid, bsmod=bsmod, fscod=fscod, cmixlev=1, surmixlev=1, dsurmod=0,
               compr=None, compr2=None, dialnorm2=None, dynrng=[], fs=[48000, 44100, 32000][fscod])
        if (acmod & 1) and acmod != 1: m.cmixlev = r.read(2)
        if acmod & 4: m.surmixlev = r.read(2)
        if acmod == 2: m.dsurmod = r.read(2)
        m.lfeon = lfeon = r.read(1); m.dialnorm = r.read(5) or 31
        if r.read(1): m.compr = r.read(8)
        if r.read(1): r.read(8)
        if r.read(1): r.read(7)
        if acmod == 0:
            m.dialnorm2 = r.read(5) or 31
            if r.read(1): m.compr2 = r.read(8)
            if r.read(1): r.read(8)
            if r.read(1): r.read(7)
        r.read(2)
        if r.read(1): r.read(14)
        if r.read(1): r.read(14)
        if r.read(1): r.read((r.read(6) + 1) * 8)
        nf = NFCHANS[acmod]
        out = np.zeros((1536, 6), np.float32)
        for blk in range(6):
            out[blk * 256:(blk + 1) * 256] = self.block(r, blk, m, fscod, acmod, nf, lfeon)
        return out, m

    def block(self, r, blk, m, fscod, acmod, nf, lfeon):
        s = self.s
        blksw = [r.read(1) for _ in range(nf)]; dith = [r.read(1) for _ in range(nf)]
        if r.read(1): s.dynrng = r.read(8)
        elif blk == 0: s.dynrng = 0
        if acmod == 0:
            if r.read(1): s.dynrng2 = r.read(8)
            elif blk == 0: s.dynrng2 = 0
        m.dynrng.append(s.dynrng)
        if r.read(1):  # cplstre
            s.cplinu = r.read(1)
            if s.cplinu:
                s.chincpl = [r.read(1) for _ in range(nf)] + [0] * (5 - nf)
                s.phsflginu = r.read(1) if acmod == 2 else 0
                s.cplbegf, s.cplendf = r.read(4), r.read(4)
                nsub = 3 + s.cplendf - s.cplbegf
                s.bstrc = [0] + [r.read(1) for _ in range(nsub - 1)]
                s.nbnd = nsub - sum(s.bstrc)
            else: s.chincpl = [0] * 5
        cplinu, chincpl = s.cplinu, s.chincpl
        nsub = 3 + s.cplendf - s.cplbegf
        cplstr, cplend = 37 + 12 * s.cplbegf, 37 + 12 * (s.cplendf + 3)
        if cplinu:
            coe = [0, 0]
            for ch in range(nf):
                if chincpl[ch] and r.read(1):
                    if ch < 2: coe[ch] = 1
                    mstr = r.read(2)
                    for b in range(s.nbnd):
                        e, mt = r.read(4), r.read(4)
                        s.cplco[ch][b] = (mt / 16 if e == 15 else (mt + 16) / 32) / 2.0 ** (e + 3 * mstr)
            if acmod == 2 and s.phsflginu and (coe[0] or coe[1]):
                s.phsflg = [r.read(1) for _ in range(s.nbnd)] + [0] * (18 - s.nbnd)
        if acmod == 2 and r.read(1):  # rematstr
            nrb = 4 if (s.cplbegf > 2 or not cplinu) else (3 if s.cplbegf > 0 else 2)
            s.remat = [r.read(1) for _ in range(nrb)] + [0] * (4 - nrb)
        cplexpstr = r.read(2) if cplinu else 0
        chexpstr = [r.read(2) for _ in range(nf)]
        lfeexpstr = r.read(1) if lfeon else 0
        for ch in range(nf):
            if chexpstr[ch] and not chincpl[ch]: s.bwcod[ch] = r.read(6)
        endmant = [cplstr if (cplinu and chincpl[ch]) else 37 + 3 * (s.bwcod[ch] + 12) for ch in range(nf)]
        if cplinu and cplexpstr:
            gs = 1 << (cplexpstr - 1)
            ng = (cplend - cplstr) // (3 * gs)
            e = decode_exps(r.read(4) << 1, [r.read(7) for _ in range(ng)], gs)
            s.cplexp = [0] * 256
            for n in range(cplend - cplstr): s.cplexp[cplstr + n] = e[n + 1]
        for ch in range(nf):
            if chexpstr[ch]:
                gs = 1 << (chexpstr[ch] - 1)
                ng = (endmant[ch] - 1 + 3 * (gs - 1)) // (3 * gs)
                e = decode_exps(r.read(4), [r.read(7) for _ in range(ng)], gs)
                s.exp[ch] = (e + [0] * 256)[:256]; r.read(2)
        if lfeon and lfeexpstr:
            s.exp[5] = (decode_exps(r.read(4), [r.read(7), r.read(7)], 1) + [0] * 256)[:256]
        if r.read(1):
            p = s.p; p.sdcycod, p.fdcycod, p.sgaincod, p.dbpbcod, p.floorcod = r.read(2), r.read(2), r.read(2), r.read(2), r.read(3)
        if r.read(1):
            s.csnr = r.read(6)
            if cplinu: s.cplfsnr, s.cplfgain = r.read(4), r.read(3)
            for ch in range(nf): s.fsnr[ch], s.fgain[ch] = r.read(4), r.read(3)
            if lfeon: s.lfefsnr, s.lfefgain = r.read(4), r.read(3)
        if cplinu and r.read(1): s.cplfleak, s.cplsleak = r.read(3), r.read(3)
        if blk == 0: s.dba = [None] * 6
        if r.read(1):
            cdb = r.read(2) if cplinu else 2
            deltbae = [r.read(2) for _ in range(nf)]
            for idx, mode in ([(5, cdb)] if cplinu else []) + list(enumerate(deltbae)):
                if mode == 1:
                    n = r.read(3) + 1
                    s.dba[idx] = [(r.read(5), r.read(4), r.read(3)) for _ in range(n)]
                elif mode == 2: s.dba[idx] = None
        if r.read(1): r.read(r.read(9) * 8)
        # allocation des bits
        zero = (s.csnr == 0 and not any(s.fsnr[:nf]) and (not cplinu or s.cplfsnr == 0) and (not lfeon or s.lfefsnr == 0))
        def snr(f): return (((s.csnr - 15) << 4) + f) << 2
        z = [0] * 256
        bap = [z if zero else calc_bap(s.exp[ch], 0, endmant[ch], fscod, s.p, s.fgain[ch], snr(s.fsnr[ch]), s.dba[ch]) for ch in range(nf)]
        cbap = z if (zero or not cplinu) else calc_bap(s.cplexp, cplstr, cplend, fscod, s.p, s.cplfgain, snr(s.cplfsnr), s.dba[5],
                                                       ((s.cplfleak << 8) + 768, (s.cplsleak << 8) + 768))
        lbap = z if (zero or not lfeon) else calc_bap(s.exp[5], 0, 7, fscod, s.p, s.lfefgain, snr(s.lfefsnr), None)
        # mantisses
        grp = {1: [], 2: [], 4: []}
        def mant(b, d):
            if b == 0:
                if not d: return 0.0
                s.seed = (s.seed * 1103515245 + 12345) & 0x7fffffff
                return (s.seed / 0x3fffffff - 1.0) * 0.707
            if b == 1 or b == 2 or b == 4:
                if not grp[b]:
                    v = r.read(7 if b != 1 else 5)
                    grp[b] = [v // 9, (v % 9) // 3, v % 3] if b == 1 else [v // 25, (v % 25) // 5, v % 5] if b == 2 else [v // 11, v % 11]
                c = grp[b].pop(0)
                return {1: Q3, 2: Q5, 4: Q11}[b][c]
            if b == 3: return Q7[r.read(3)]
            if b == 5: return Q15[r.read(4)]
            n = QNTZ[b]; v = r.read(n)
            return (v - (1 << n) if v >> (n - 1) else v) / (1 << (n - 1))
        X = np.zeros((6, 256)); cplc = np.zeros(256); got = False
        for ch in range(nf):
            e, b = s.exp[ch], bap[ch]
            X[ch, :endmant[ch]] = [mant(b[k], dith[ch]) * P2[e[k]] for k in range(endmant[ch])]
            if cplinu and chincpl[ch] and not got:
                cplc[cplstr:cplend] = [mant(cbap[k], 0) * P2[s.cplexp[k]] for k in range(cplstr, cplend)]; got = True
        if lfeon: X[5, :7] = [mant(lbap[k], 0) * P2[s.exp[5][k]] for k in range(7)]
        bw = [cplend if (cplinu and chincpl[ch]) else endmant[ch] for ch in range(nf)]
        if cplinu:
            bmap, b_ = [], -1
            for i in range(nsub):
                if i == 0 or not s.bstrc[i]: b_ += 1
                bmap.append(b_)
            for ch in range(nf):
                if chincpl[ch]:
                    cc = cplc.copy()
                    if dith[ch]:  # bruit de remplissage (bap = 0), indépendant par canal, après décomposition
                        zb = np.array(cbap[cplstr:cplend]) == 0
                        sc = np.array([P2[s.cplexp[k]] for k in range(cplstr, cplend)])
                        cc[cplstr:cplend][zb] = self.rng.uniform(-0.707, 0.707, int(zb.sum())) * sc[zb]
                    for i in range(nsub):
                        lo = cplstr + 12 * i; bi = bmap[i]
                        sg = -1.0 if (ch == 1 and acmod == 2 and s.phsflg[bi]) else 1.0
                        X[ch, lo:lo + 12] = cc[lo:lo + 12] * s.cplco[ch][bi] * 8 * sg
        if acmod == 2 and any(s.remat):
            edges = [13, 25, 37, 61, 253] if (not cplinu or s.cplbegf > 2) else ([13, 25, 37, cplstr] if s.cplbegf > 0 else [13, 25, 37])
            if cplinu and s.cplbegf > 2: edges[4] = cplstr
            for i in range(len(edges) - 1):
                if s.remat[i]:
                    lo, hi = edges[i], min(edges[i + 1], bw[0], bw[1])
                    a, c = X[0, lo:hi].copy(), X[1, lo:hi].copy()
                    X[0, lo:hi], X[1, lo:hi] = a + c, a - c
        # compression dynamique
        for ch in range(nf):
            if self.drc == "none": break
            word, bits = (s.dynrng2 if (acmod == 0 and ch == 1) else s.dynrng), 3
            cw = m.compr2 if (acmod == 0 and ch == 1) else m.compr
            if self.drc == "compr" and cw is not None: word, bits = cw, 4
            g = dyn_gain(word, bits)
            X[ch] *= g ** (self.cut if g < 1 else self.boost)
        pcm = np.zeros((256, 6))
        for ch in list(range(nf)) + ([5] if lfeon else []):
            y, self.delay[ch] = imdct(X[ch], ch < nf and blksw[ch], self.delay[ch])
            cols = OUTMAP[acmod][ch] if ch < nf else [3]
            for c in cols: pcm[:, c] = y
        return pcm
