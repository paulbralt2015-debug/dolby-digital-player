# Lecteur Dolby Digital (AC-3) — décodeur écrit à la main
Décodeur AC-3 en Python/NumPy d'après ATSC A/52:2018 (`ac3/decoder.py`), tables extraites de la norme par `tools_gen_tables.py`.
Effets : dialnorm, compression dynamique (dynrng/compr), mixage LoRo / LtRt (Dolby Surround) / mono / 5.1, surround virtuel (5.1 -> stéréo 3D, `ac3/virtual.py`, modèle binaural libre).
Lecteur : plein écran (F / F11 / double-clic, Échap pour sortir), boucle (L), format d'image (A : Auto, 16:9, 4:3, 21:9, 1:1, remplir, étirer), pause (Espace).
Sources prises en charge : .ac3, MP4/MOV, MKV/WebM, VOB/MPEG-PS, TS/M2TS (pistes AC-3). Non pris en charge : E-AC-3, TrueHD, Atmos, MPEG-1 System.
Lecture en continu : le décodage se fait à la demande (flux WAV virtuel fourni à libmpv), sans attente ni fichier temporaire ; le déplacement dans le film est géré (index PTS pour VOB/TS).
La vidéo est lue par libmpv (qui contient ses propres bibliothèques vidéo) ; l'audio AC-3 n'utilise aucun code FFmpeg.
Build : onglet Actions > "Build Windows" > Run workflow. Local : `pip install -r requirements.txt`, `libmpv-2.dll` à côté de main.py, `python main.py`.
Tests (FFmpeg requis, test uniquement) : `python tools_test.py`, `tools_test2.py`, `tools_test3.py`.
