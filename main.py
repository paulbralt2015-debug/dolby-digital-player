import os, sys, locale
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
os.environ["PATH"] = str(BASE) + os.pathsep + os.environ.get("PATH", "")
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(BASE))

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)
locale.setlocale(locale.LC_NUMERIC, "C")
import mpv
from ac3.source import Source
from ac3.stream import Ac3Stream

MODES = {"Stéréo (LoRo)": "loro", "Surround virtuel (casque / 2 enceintes)": "virtual",
         "Stéréo Dolby Surround (LtRt)": "ltrt", "5.1": "5.1", "Mono": "mono"}
DRCS = {"Compression standard": "dynrng", "Compression forte": "compr", "Aucune": "none"}
ASPECTS = ["Auto", "16:9", "4:3", "21:9", "1:1", "Remplir (rogner)", "Étirer"]


class Win(QWidget):
    req = Signal(str)      # actions venant des touches de la fenêtre vidéo mpv (autre thread)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lecteur Dolby Digital (décodeur AC-3 intégré)"); self.resize(1050, 700)
        self.path = self.ext_id = self.orig_aid = self.src = self.cfg = None; self.n = 0; self.dur = None
        self.video = QWidget(); self.video.setStyleSheet("background:black"); self.video.setAttribute(Qt.WA_NativeWindow)
        self.p = mpv.MPV(wid=str(int(self.video.winId())), input_default_bindings=False, input_vo_keyboard=True,
                         keep_open="yes", ytdl=False)
        bo, bp = QPushButton("Ouvrir…"), QPushButton("Lecture / Pause")
        self.bfs = QPushButton("Plein écran (F)")
        self.loop = QCheckBox("Boucle (L)")
        self.asp = QComboBox(); self.asp.addItems(ASPECTS)
        self.chk = QCheckBox("Décodeur Dolby Digital")
        self.mode, self.drc = QComboBox(), QComboBox(); self.mode.addItems(MODES); self.drc.addItems(DRCS)
        self.dn = QCheckBox("Dialnorm"); self.dn.setChecked(True)
        self.tgt = QSpinBox(); self.tgt.setRange(-40, -10); self.tgt.setValue(-27); self.tgt.setSuffix(" dBFS")
        self.lbl = QLabel("")
        self.seek = QSlider(Qt.Horizontal); self.seek.setRange(0, 1000)
        self.vol = QSlider(Qt.Horizontal); self.vol.setRange(0, 100); self.vol.setValue(80); self.vol.setMaximumWidth(110)
        r1, r2, r3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for w in (bo, bp, self.bfs, self.loop, QLabel("Format d'image :"), self.asp): r1.addWidget(w)
        for w in (self.chk, self.mode, self.drc, self.dn, self.tgt): r2.addWidget(w)
        for w in (self.lbl, QLabel("Vol."), self.vol): r3.addWidget(w)
        self.controls = QWidget(); cl = QVBoxLayout(self.controls); cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.seek); cl.addLayout(r1); cl.addLayout(r2); cl.addLayout(r3)
        lay = QVBoxLayout(self); lay.addWidget(self.video, 1); lay.addWidget(self.controls)
        bo.clicked.connect(self.open_file); bp.clicked.connect(self.toggle_pause); self.bfs.clicked.connect(self.toggle_fs)
        self.loop.toggled.connect(self.set_loop); self.asp.currentIndexChanged.connect(self.set_aspect)
        self.chk.toggled.connect(self.refresh)
        for w in (self.mode, self.drc): w.currentIndexChanged.connect(self.refresh)
        self.dn.toggled.connect(self.refresh); self.tgt.editingFinished.connect(self.refresh)
        self.seek.sliderMoved.connect(lambda v: self.p.duration and self.p.seek(v / 1000 * self.p.duration, "absolute"))
        self.vol.valueChanged.connect(lambda v: setattr(self.p, "volume", v)); self.p.volume = 80
        # raccourcis : fenêtre Qt + fenêtre vidéo mpv (quand elle a le focus)
        for key, act in (("F", "fs"), ("F11", "fs"), ("Esc", "exit"), ("L", "loop"), ("A", "aspect"), ("Space", "pause")):
            QShortcut(QKeySequence(key), self, activated=lambda a=act: self.on_req(a))
        self.req.connect(self.on_req)
        self.p.register_message_handler("ac3", lambda *a: self.req.emit(a[0] if a else ""))
        for key, act in (("f", "fs"), ("ESC", "exit"), ("l", "loop"), ("a", "aspect"), ("SPACE", "pause"), ("MBTN_LEFT_DBL", "fs")):
            self.p.command("keybind", key, f"script-message ac3 {act}")
        self.p.register_stream_protocol("ac3dec", self.open_stream)
        t = QTimer(self); t.timeout.connect(self.tick); t.start(250)

    # ---- actions ----
    def on_req(self, act):
        if act == "fs": self.toggle_fs()
        elif act == "exit" and self.isFullScreen(): self.toggle_fs()
        elif act == "loop": self.loop.setChecked(not self.loop.isChecked())
        elif act == "aspect": self.asp.setCurrentIndex((self.asp.currentIndex() + 1) % len(ASPECTS))
        elif act == "pause": self.toggle_pause()

    def toggle_pause(self): self.p.pause = not self.p.pause

    def toggle_fs(self):
        if self.isFullScreen(): self.controls.show(); self.showNormal()
        else: self.controls.hide(); self.showFullScreen()

    def set_loop(self, on): self.p.loop_file = "inf" if on else "no"

    def set_aspect(self, i):
        name = ASPECTS[i]
        self.p.keepaspect = name != "Étirer"
        self.p.panscan = 1.0 if name.startswith("Remplir") else 0.0
        self.p.video_aspect_override = name if ":" in name else "no"

    # ---- fichier et audio ----
    def open_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Ouvrir une vidéo")
        if not f: return
        self.path, self.ext_id, self.src = f, None, None
        self.chk.blockSignals(True); self.chk.setChecked(False); self.chk.blockSignals(False)
        self.p.play(f); self.p.wait_until_playing()
        self.set_loop(self.loop.isChecked()); self.set_aspect(self.asp.currentIndex())
        tr = [t for t in self.p.track_list if t["type"] == "audio"]
        self.orig_aid = tr[0]["id"] if tr else None
        try:
            self.src = Source(f, 0); self.lbl.setText("Piste Dolby Digital détectée")
        except Exception as e:
            self.lbl.setText("Pas de piste AC-3 lisible : " + str(e))

    def opts(self):
        return dict(mode=MODES[self.mode.currentText()], drc=DRCS[self.drc.currentText()],
                    dialnorm=self.dn.isChecked(), target=float(self.tgt.value()))

    def open_stream(self, uri):
        """Appelé par libmpv : flux WAV virtuel décodé à la demande (aucune attente)."""
        if self.src is None: raise ValueError("pas de source AC-3")
        return Ac3Stream(self.src, duration_hint=self.dur, **self.cfg)

    def refresh(self, *_):
        if not self.path: return
        if not self.chk.isChecked():
            if self.orig_aid is not None: self.p.aid = self.orig_aid
            return
        if self.src is None:
            self.lbl.setText("Aucune piste AC-3 : décodeur indisponible")
            self.chk.blockSignals(True); self.chk.setChecked(False); self.chk.blockSignals(False); return
        self.cfg = self.opts(); self.dur = self.p.duration; self.n += 1; old = self.ext_id
        try:   # décalage entre le début de l'audio et celui du fichier (TS / VOB)
            self.p.audio_delay = float(self.src.t0 - (self.p.demuxer_start_time or 0.0)) if self.src.t0 else 0.0
        except Exception: pass
        self.p.command("audio-add", f"ac3dec://s{self.n}", "select")
        ext = [t["id"] for t in self.p.track_list if t["type"] == "audio" and t.get("external")]
        self.ext_id = ext[-1] if ext else None
        if old is not None:
            try: self.p.command("audio-remove", old)
            except Exception: pass
        self.lbl.setText("Décodeur AC-3 intégré actif (lecture en continu)")

    def tick(self):
        d, t = self.p.duration, self.p.time_pos
        if d and t is not None and not self.seek.isSliderDown(): self.seek.setValue(int(t / d * 1000))

    def closeEvent(self, e):
        self.p.terminate(); super().closeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv); w = Win(); w.show(); sys.exit(app.exec())
