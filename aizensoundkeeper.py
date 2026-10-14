"""
AizenSoundKeeper v2.0
═══════════════════════════════════════════════════════════════════════════
Maintient tes baffes en vie + ciblage multi-device + veille Windows + DSP.

Auteur  : AizenOS / Antigravity
Licence : MIT
AI Noise Cancellation : désactivé (toute implémentation temps-réel
                        ajoute ≥10 ms de latence — directive utilisateur).
═══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import sys, os, threading, time, json, logging, math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import ctypes
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import sounddevice as sd

try:
    import pystray
    from pystray import MenuItem as TrayItem
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# ──────────────────────────────────────────────────────────────────────────────
APP_NAME    = "AizenSoundKeeper"
VERSION     = "2.0.0"
SAMPLE_RATE = 44100
CHANNELS    = 2
BLOCK_SIZE  = 512
DEFAULT_DB  = -72.0
CONFIG_PATH = Path(os.getenv("APPDATA", ".")) / "AizenSoundKeeper" / "config.json"
DIGITAL_KW  = frozenset(["digital","spdif","s/pdif","hdmi","optical","toslink","coaxial"])

def get_resource_path(relative_path: str) -> Path:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return Path(base) / relative_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(APP_NAME)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_CFG: dict = {
    "amplitude_db": DEFAULT_DB,
    "device_mode": "Primary",      # Primary | All | Digital | Analog | Marked | Manual
    "manual_devices": [],
    "sleep_mode": "Off",           # Off | SleepD | SleepL | Sleepy
    "dsp": {
        "enabled": False,
        "hpf":        {"enabled": True,  "freq": 40,   "q": 0.707},
        "bass_boost": {"enabled": False, "freq": 80,   "gain_db": 4.0, "q": 0.707},
        "presence":   {"enabled": False, "freq": 3000, "gain_db": 2.5, "q": 1.5},
        "compressor": {
            "enabled": False,
            "threshold_db": -24.0, "ratio": 3.0,
            "attack_ms": 50.0, "release_ms": 200.0, "makeup_db": 6.0,
        },
    },
}


def _deep_merge(base: dict, patch: dict) -> dict:
    result = base.copy()
    for k, v in patch.items():
        result[k] = _deep_merge(base[k], v) if isinstance(v, dict) and k in base else v
    return result


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return _deep_merge(DEFAULT_CFG, json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception as e:
            log.warning("Config load error: %s", e)
    return _deep_merge(DEFAULT_CFG, {})


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), "utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  DSP — FILTRES BIQUAD IIR (Audio EQ Cookbook, RBJ) — ZÉRO LATENCE
# ══════════════════════════════════════════════════════════════════════════════

class Biquad:
    """Direct Form II transposed — zéro latence algorithmique."""

    def __init__(self, b0: float, b1: float, b2: float, a1: float, a2: float) -> None:
        self.b = np.array([b0, b1, b2], dtype=np.float64)
        self.a = np.array([a1, a2],     dtype=np.float64)
        self.z = np.zeros((2, CHANNELS), dtype=np.float64)

    def process(self, x: np.ndarray) -> np.ndarray:
        b0, b1, b2 = self.b
        a1, a2     = self.a
        y = np.empty_like(x, dtype=np.float64)
        z = self.z
        for n in range(len(x)):
            for c in range(x.shape[1]):
                yn = b0 * x[n, c] + z[0, c]
                z[0, c] = b1 * x[n, c] - a1 * yn + z[1, c]
                z[1, c] = b2 * x[n, c] - a2 * yn
                y[n, c] = yn
        return y

    @staticmethod
    def hpf(freq: float, q: float = 0.707, fs: int = SAMPLE_RATE) -> "Biquad":
        w0 = 2 * math.pi * freq / fs
        cw = math.cos(w0); sw = math.sin(w0)
        alpha = sw / (2 * q)
        b0 =  (1 + cw) / 2;  b1 = -(1 + cw);  b2 = (1 + cw) / 2
        a0 = 1 + alpha;       a1 = -2 * cw;     a2 = 1 - alpha
        return Biquad(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)

    @staticmethod
    def low_shelf(freq: float, gain_db: float, q: float = 0.707, fs: int = SAMPLE_RATE) -> "Biquad":
        A  = 10 ** (gain_db / 40)
        w0 = 2 * math.pi * freq / fs
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2 * q) * math.sqrt((A + 1/A) * (1/0.9 - 1) + 2)
        s2A = 2 * math.sqrt(A) * alpha
        b0 =     A * ((A+1) - (A-1)*cw + s2A)
        b1 = 2 * A * ((A-1) - (A+1)*cw)
        b2 =     A * ((A+1) - (A-1)*cw - s2A)
        a0 =         ((A+1) + (A-1)*cw + s2A)
        a1 = -2 *    ((A-1) + (A+1)*cw)
        a2 =         ((A+1) + (A-1)*cw - s2A)
        return Biquad(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)

    @staticmethod
    def peaking(freq: float, gain_db: float, q: float = 1.5, fs: int = SAMPLE_RATE) -> "Biquad":
        A  = 10 ** (gain_db / 40)
        w0 = 2 * math.pi * freq / fs
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2 * q)
        b0 = 1 + alpha * A;   b1 = -2 * cw;   b2 = 1 - alpha * A
        a0 = 1 + alpha / A;   a1 = -2 * cw;   a2 = 1 - alpha / A
        return Biquad(b0/a0, b1/a0, b2/a0, a1/a0, a2/a0)


class RMSCompressor:
    """Feedforward RMS — pas de look-ahead, zéro latence ajoutée."""

    def __init__(self, threshold_db: float, ratio: float,
                 attack_ms: float, release_ms: float, makeup_db: float,
                 fs: int = SAMPLE_RATE) -> None:
        self.threshold = 10 ** (threshold_db / 20)
        self.ratio     = max(ratio, 1.0)
        self.makeup    = 10 ** (makeup_db / 20)
        at  = attack_ms  / 1000
        rt  = release_ms / 1000
        self.att_c = math.exp(-1 / (fs * at))  if at  > 0 else 0.0
        self.rel_c = math.exp(-1 / (fs * rt))  if rt  > 0 else 0.0
        self._env  = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        out = np.empty_like(x, dtype=np.float64)
        env = self._env
        for n in range(len(x)):
            rms  = math.sqrt(float(np.mean(x[n] ** 2)) + 1e-12)
            c    = self.att_c if rms > env else self.rel_c
            env  = c * env + (1 - c) * rms
            gain = ((self.threshold + (env - self.threshold) / self.ratio) / env
                    if env > self.threshold else 1.0)
            out[n] = x[n] * gain * self.makeup
        self._env = env
        return out


class DSPChain:
    """Chaîne DSP ordonnée construite depuis la config."""

    def __init__(self, dsp_cfg: dict) -> None:
        self._stages: List = []
        self._preamp: float = 1.0
        self._rebuild(dsp_cfg)

    def _rebuild(self, dsp_cfg: dict) -> None:
        self._stages = []
        self._preamp = 1.0
        if not dsp_cfg.get("enabled"):
            return
        c = dsp_cfg
        if c["hpf"]["enabled"]:
            self._stages.append(Biquad.hpf(c["hpf"]["freq"], c["hpf"]["q"]))
        if c["bass_boost"]["enabled"]:
            bb = c["bass_boost"]
            self._preamp *= 10 ** (-bb["gain_db"] / 2 / 20)   # pré-gain anti-clipping
            self._stages.append(Biquad.low_shelf(bb["freq"], bb["gain_db"], bb["q"]))
        if c["presence"]["enabled"]:
            p = c["presence"]
            self._stages.append(Biquad.peaking(p["freq"], p["gain_db"], p["q"]))
        if c["compressor"]["enabled"]:
            cp = c["compressor"]
            self._stages.append(RMSCompressor(
                cp["threshold_db"], cp["ratio"],
                cp["attack_ms"], cp["release_ms"], cp["makeup_db"],
            ))
        log.info("DSP chain: %d étage(s) — préamp=%.2f", len(self._stages), self._preamp)

    def update(self, dsp_cfg: dict) -> None:
        self._rebuild(dsp_cfg)

    def process(self, x: np.ndarray) -> np.ndarray:
        if not self._stages:
            return x
        y = x.astype(np.float64) * self._preamp
        for stage in self._stages:
            y = stage.process(y)
        return np.clip(y, -1.0, 1.0).astype(np.float32)


# ══════════════════════════════════════════════════════════════════════════════
#  DEVICE MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class DeviceManager:

    @staticmethod
    def all_outputs() -> List[Tuple[int, str]]:
        return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                if d["max_output_channels"] > 0]

    @staticmethod
    def default_output() -> Optional[int]:
        try:
            return int(sd.default.device[1])
        except Exception:
            return None

    @staticmethod
    def resolve(mode: str, manual: List[int]) -> List[int]:
        devs = sd.query_devices()
        outs = [(i, devs[i]) for i in range(len(devs)) if devs[i]["max_output_channels"] > 0]

        if mode == "Primary":
            idx = DeviceManager.default_output()
            return [idx] if idx is not None else []

        if mode == "All":
            return [i for i, _ in outs]

        if mode == "Digital":
            return [i for i, d in outs
                    if any(kw in d["name"].lower() for kw in DIGITAL_KW)]

        if mode == "Analog":
            return [i for i, d in outs
                    if not any(kw in d["name"].lower() for kw in DIGITAL_KW)]

        if mode == "Marked":
            return [i for i, d in outs if "!" in d["name"]]

        if mode == "Manual":
            return [i for i in manual
                    if i < len(devs) and devs[i]["max_output_channels"] > 0]

        return []


# ══════════════════════════════════════════════════════════════════════════════
#  SLEEP MONITOR — polling ctypes, 0 dépendance win32
# ══════════════════════════════════════════════════════════════════════════════

class SleepMonitor:

    def __init__(self, on_sleep: Callable, on_wake: Callable, mode: str = "Off") -> None:
        self.mode      = mode
        self.on_sleep  = on_sleep
        self.on_wake   = on_wake
        self._sleeping = False
        self._stop     = threading.Event()
        self._thread   = threading.Thread(
            target=self._run, daemon=True, name="SleepMonitor")

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── Windows state detectors ──────────────────────────────────────────────

    @staticmethod
    def _locked() -> bool:
        try:
            h = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
            if h:
                ctypes.windll.user32.CloseDesktop(h)
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _screen_off() -> bool:
        # SPI_GETSCREENSAVERRUNNING = 0x0072
        running = ctypes.c_int(0)
        ctypes.windll.user32.SystemParametersInfoW(0x0072, 0, ctypes.byref(running), 0)
        return bool(running.value)

    def _should_sleep(self) -> bool:
        if self.mode == "Off":
            return False
        locked = self._locked()     if self.mode in ("SleepL", "Sleepy") else False
        s_off  = self._screen_off() if self.mode in ("SleepD", "Sleepy") else False
        return locked or s_off

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(2)
            s = self._should_sleep()
            if s and not self._sleeping:
                self._sleeping = True
                log.info("SleepMonitor → SLEEP (%s)", self.mode)
                try:    self.on_sleep()
                except Exception as e: log.error("on_sleep: %s", e)
            elif not s and self._sleeping:
                self._sleeping = False
                log.info("SleepMonitor → WAKE")
                try:    self.on_wake()
                except Exception as e: log.error("on_wake: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  AUDIO ENGINE — multi-stream, un stream par device cible
# ══════════════════════════════════════════════════════════════════════════════

class AudioEngine:

    def __init__(self, cfg: dict) -> None:
        self.cfg       = cfg
        self._streams: Dict[int, sd.OutputStream] = {}
        self._lock     = threading.Lock()
        self._dsp      = DSPChain(cfg["dsp"])
        self.active    = False
        self._rebuild_buffer()

    # ── Buffer ────────────────────────────────────────────────────────────────

    def _rebuild_buffer(self) -> None:
        amp = 10 ** (self.cfg.get("amplitude_db", DEFAULT_DB) / 20)
        rng = np.random.default_rng(42)
        raw = (rng.uniform(-1., 1., (BLOCK_SIZE, CHANNELS)) * amp).astype(np.float32)
        self._buffer: np.ndarray = self._dsp.process(raw)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self.active:
                return
            targets = DeviceManager.resolve(
                self.cfg["device_mode"], self.cfg.get("manual_devices", []))
            if not targets:
                log.warning("Aucun device cible (mode=%s).", self.cfg["device_mode"])
            self.active = True
            for idx in targets:
                self._open(idx)

    def _open(self, idx: int) -> None:
        if idx in self._streams:
            return
        try:
            info = sd.query_devices(idx)
            ch   = min(CHANNELS, int(info["max_output_channels"]))
            s    = sd.OutputStream(
                device=idx, samplerate=SAMPLE_RATE,
                channels=ch, dtype="float32", blocksize=BLOCK_SIZE,
                callback=self._make_cb(idx, ch),
                finished_callback=lambda i=idx: self._on_finished(i),
            )
            s.start()
            self._streams[idx] = s
            log.info("▶ [%d] %s — %dch", idx, info["name"][:50], ch)
        except Exception as e:
            log.error("Open stream[%d]: %s", idx, e)

    def _make_cb(self, idx: int, ch: int) -> Callable:
        def _cb(out, frames, t, status):
            if status:
                log.debug("Stream[%d]: %s", idx, status)
            src = self._buffer[:frames, :ch]
            if src.shape == out.shape:
                out[:] = src
            else:
                out.fill(0)
        return _cb

    def _on_finished(self, idx: int) -> None:
        with self._lock:
            self._streams.pop(idx, None)
            if self.active:
                log.warning("Stream[%d] terminé — retry 2s…", idx)
                threading.Timer(2.0, lambda: self._open(idx)).start()

    def stop(self) -> None:
        with self._lock:
            self.active = False
            for idx, s in list(self._streams.items()):
                try:
                    s.stop(); s.close()
                except Exception as e:
                    log.debug("Stop[%d]: %s", idx, e)
            self._streams.clear()
            log.info("⏹ Tous les streams fermés.")

    def update_config(self, cfg: dict) -> None:
        was = self.active
        self.stop()
        self.cfg = cfg
        self._dsp.update(cfg["dsp"])
        self._rebuild_buffer()
        if was:
            self.start()

    @property
    def device_count(self) -> int:
        return len(self._streams)


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS WINDOW — tkinter tabbé (doit tourner dans le thread principal)
# ══════════════════════════════════════════════════════════════════════════════

class SettingsWindow:
    # Palette
    BG    = "#12121f"; BG2  = "#1a1a2e"; BG3  = "#0f0f1a"
    ACC   = "#0f3460"; HL   = "#e94560"; HL2  = "#ff6b35"
    FG    = "#eaeaea"; FG2  = "#888899"
    FNT   = ("Segoe UI", 10)
    FNT_B = ("Segoe UI Semibold", 10)
    FNT_H = ("Segoe UI Semibold", 14)
    FNT_S = ("Segoe UI", 9)
    FNT_C = ("Consolas", 9)

    def __init__(self, cfg: dict, on_apply: Callable) -> None:
        self.cfg      = cfg
        self.on_apply = on_apply
        self._root: Optional[tk.Tk]      = None
        self._win:  Optional[tk.Toplevel] = None

    def set_root(self, root: tk.Tk) -> None:
        self._root = root

    def show(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.lift(); self._win.focus_force(); return
        self._build()

    def hide(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        win = tk.Toplevel(self._root)
        win.title(f"{APP_NAME}  ·  Paramètres")
        win.configure(bg=self.BG)
        win.geometry("680x600")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self._win = win

        ico_file = get_resource_path("aizensoundkeeper.ico")
        if ico_file.exists():
            try:
                win.iconbitmap(str(ico_file))
            except Exception:
                pass

        # Accent bar
        tk.Frame(win, bg=self.HL, height=3).pack(fill="x")

        # Header
        tk.Label(win, text=f"⚡  {APP_NAME}",
                 bg=self.BG, fg=self.HL, font=self.FNT_H).pack(pady=(10, 0))
        tk.Label(win, text="Maintient tes baffes en vie — toujours.",
                 bg=self.BG, fg=self.FG2, font=self.FNT_S).pack()

        # Style
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TNotebook",       background=self.BG,  borderwidth=0)
        s.configure("TNotebook.Tab",   background=self.ACC, foreground=self.FG,
                    font=self.FNT_B,   padding=[14, 6])
        s.map("TNotebook.Tab",         background=[("selected", self.HL)],
                                       foreground=[("selected", "#fff")])
        s.configure("TFrame",          background=self.BG2)
        s.configure("TLabelframe",     background=self.BG2, foreground=self.FG)
        s.configure("TLabelframe.Label", font=self.FNT_B,  foreground=self.HL)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=10, pady=6)

        tabs = [
            ("🔈  Périphériques", self._tab_devices),
            ("💤  Veille",        self._tab_sleep),
            ("🎚  DSP Audio",     self._tab_dsp),
            ("ℹ  À propos",      self._tab_about),
        ]
        for label, builder in tabs:
            f = ttk.Frame(nb); nb.add(f, text=label); builder(f)

        # Buttons
        bf = tk.Frame(win, bg=self.BG)
        bf.pack(fill="x", padx=12, pady=8)
        self._status = tk.Label(bf, text="", bg=self.BG, fg=self.HL2, font=self.FNT_S)
        self._status.pack(side="left")
        tk.Button(bf, text="Fermer", command=win.withdraw,
                  bg=self.ACC, fg=self.FG, font=self.FNT,
                  relief="flat", padx=12, pady=5,
                  cursor="hand2").pack(side="right", padx=4)
        tk.Button(bf, text="✅  Appliquer", command=self._apply,
                  bg=self.HL, fg="#fff", font=self.FNT_B,
                  relief="flat", padx=16, pady=5,
                  cursor="hand2").pack(side="right", padx=4)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _lf(self, parent: tk.Widget, title: str) -> tk.LabelFrame:
        f = tk.LabelFrame(parent, text=f"  {title}  ",
                          bg=self.BG2, fg=self.HL, font=self.FNT_B,
                          relief="flat", bd=1, highlightbackground=self.ACC)
        f.pack(fill="x", padx=8, pady=4)
        return f

    def _radio_row(self, parent, var, value, label, desc) -> None:
        row = tk.Frame(parent, bg=self.BG2); row.pack(fill="x", pady=1, padx=4)
        tk.Radiobutton(row, text=label, variable=var, value=value,
                       bg=self.BG2, fg=self.FG, selectcolor=self.ACC,
                       activebackground=self.BG2, font=self.FNT_B,
                       cursor="hand2").pack(side="left", padx=4)
        tk.Label(row, text=desc, bg=self.BG2, fg=self.FG2,
                 font=self.FNT_S).pack(side="left")

    def _check_row(self, parent, var, label, desc="") -> None:
        row = tk.Frame(parent, bg=self.BG2); row.pack(fill="x", pady=1, padx=4)
        tk.Checkbutton(row, text=label, variable=var,
                       bg=self.BG2, fg=self.FG, selectcolor=self.ACC,
                       activebackground=self.BG2, font=self.FNT_B,
                       cursor="hand2").pack(side="left", padx=4)
        if desc:
            tk.Label(row, text=desc, bg=self.BG2, fg=self.FG2,
                     font=self.FNT_S).pack(side="left")

    def _slider(self, parent, label, var, lo, hi, unit="", fmt="{:.0f}",
                res: float = 0.5) -> None:
        row = tk.Frame(parent, bg=self.BG2); row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text=label, bg=self.BG2, fg=self.FG, font=self.FNT,
                 width=24, anchor="w").pack(side="left")
        val_lbl = tk.Label(row, text=fmt.format(var.get()) + unit,
                           bg=self.BG2, fg=self.HL2, font=self.FNT_B, width=9)
        val_lbl.pack(side="right")
        def _upd(v): val_lbl.config(text=fmt.format(float(v)) + unit)
        tk.Scale(row, variable=var, from_=lo, to=hi, orient="horizontal",
                 bg=self.BG2, fg=self.FG, troughcolor=self.ACC,
                 highlightthickness=0, showvalue=False, resolution=res,
                 command=_upd, cursor="hand2").pack(side="left", fill="x", expand=True, padx=4)

    def _note(self, parent, text, color=None) -> None:
        tk.Label(parent, text=text, bg=self.BG2, fg=color or self.FG2,
                 font=self.FNT_S, wraplength=580, justify="left"
                 ).pack(anchor="w", padx=10, pady=(0, 4))

    # ── Tab : Périphériques ───────────────────────────────────────────────────

    def _tab_devices(self, parent: ttk.Frame) -> None:
        # Targeting mode
        self._mode_var = tk.StringVar(value=self.cfg.get("device_mode", "Primary"))
        lf = self._lf(parent, "🎯 Mode de ciblage")
        modes = [
            ("Primary", "🎯 Primary",
             "Sortie principale active Windows (défaut)"),
            ("All",     "📡 All",
             "Toutes les sorties actives — ex. SteelSeries Sonar"),
            ("Digital", "💿 Digital",
             "SPDIF / HDMI / Optical uniquement"),
            ("Analog",  "📻 Analog",
             "Analogique / Bluetooth uniquement (WZ-BT5.0)"),
            ("Marked",  "❗ Marked",
             "Sorties dont le nom contient  !  (ex: '!Mes Baffes')"),
            ("Manual",  "🔧 Manuel",
             "Sélection manuelle ci-dessous"),
        ]
        for val, lbl, desc in modes:
            self._radio_row(lf, self._mode_var, val, lbl, desc)

        # Manual list
        lf2 = self._lf(parent, "🔧 Sélection manuelle (mode Manuel)")
        manual = self.cfg.get("manual_devices", [])
        self._manual_vars: Dict[int, tk.BooleanVar] = {}

        outer = tk.Frame(lf2, bg=self.BG2); outer.pack(fill="both", expand=True)
        cv = tk.Canvas(outer, bg=self.BG2, highlightthickness=0, height=100)
        sb = tk.Scrollbar(outer, orient="vertical", command=cv.yview,
                          bg=self.BG3, troughcolor=self.ACC)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); cv.pack(fill="both", expand=True)
        inner = tk.Frame(cv, bg=self.BG2)
        cv.create_window((0, 0), window=inner, anchor="nw")

        for idx, name in DeviceManager.all_outputs():
            v = tk.BooleanVar(value=(idx in manual))
            self._manual_vars[idx] = v
            tk.Checkbutton(inner, text=f"[{idx}]  {name[:60]}",
                           variable=v, bg=self.BG2, fg=self.FG,
                           selectcolor=self.ACC, activebackground=self.BG2,
                           font=self.FNT, cursor="hand2").pack(anchor="w", padx=4)
        inner.update_idletasks()
        cv.configure(scrollregion=cv.bbox("all"))
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))

        # Amplitude
        self._amp_var = tk.DoubleVar(value=self.cfg.get("amplitude_db", DEFAULT_DB))
        lf3 = self._lf(parent, "🔉 Amplitude du signal muet")
        self._slider(lf3, "Niveau keepalive", self._amp_var, -96, -36, " dB", "{:.0f}")
        self._note(lf3,
                   "💡  -72 dB = inaudible garanti. Monter à -60 dB si tes baffes ne réagissent pas.")

    # ── Tab : Veille ──────────────────────────────────────────────────────────

    def _tab_sleep(self, parent: ttk.Frame) -> None:
        self._sleep_var = tk.StringVar(value=self.cfg.get("sleep_mode", "Off"))
        lf = self._lf(parent, "💤 Mode veille")
        modes = [
            ("Off",    "⚡ Off",    "AizenSoundKeeper tourne en permanence"),
            ("SleepD", "🖥 SleepD", "Pause quand l'écran s'éteint"),
            ("SleepL", "🔒 SleepL", "Pause quand la session est verrouillée (Win+L)"),
            ("Sleepy", "💤 Sleepy", "Pause si écran éteint  OU  session verrouillée"),
        ]
        for val, lbl, desc in modes:
            self._radio_row(lf, self._sleep_var, val, lbl, desc)
        self._note(lf,
                   "ℹ️  Détection via SPI_GETSCREENSAVERRUNNING + OpenInputDesktop().\n"
                   "Polling toutes les 2 secondes. Compatible Windows 10 / 11.")

    # ── Tab : DSP ─────────────────────────────────────────────────────────────

    def _tab_dsp(self, parent: ttk.Frame) -> None:
        dsp = self.cfg["dsp"]

        cv = tk.Canvas(parent, bg=self.BG2, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=cv.yview,
                          bg=self.BG3, troughcolor=self.ACC)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); cv.pack(fill="both", expand=True)
        inner = tk.Frame(cv, bg=self.BG2)
        win_id = cv.create_window((0, 0), window=inner, anchor="nw")

        def _resize(e): cv.itemconfig(win_id, width=e.width)
        cv.bind("<Configure>", _resize)
        inner.bind("<Configure>",
                   lambda e: cv.configure(scrollregion=cv.bbox("all")))

        def section(icon, title, desc):
            lf = tk.LabelFrame(inner, text=f"  {icon}  {title}  ",
                               bg=self.BG2, fg=self.HL, font=self.FNT_B,
                               relief="flat", bd=1, highlightbackground=self.ACC)
            lf.pack(fill="x", padx=8, pady=4)
            self._note(lf, desc)
            return lf

        # Master DSP switch
        self._dsp_en = tk.BooleanVar(value=dsp.get("enabled", False))
        top = tk.Frame(inner, bg=self.BG2); top.pack(fill="x", padx=8, pady=4)
        tk.Checkbutton(top, text="⚡  Activer le traitement DSP",
                       variable=self._dsp_en, bg=self.BG2, fg=self.FG,
                       selectcolor=self.ACC, activebackground=self.BG2,
                       font=self.FNT_B, cursor="hand2").pack(anchor="w")
        tk.Label(top, text="⚠  Filtres IIR biquad — zéro latence ajoutée. "
                            "Appliqués au signal keepalive.",
                 bg=self.BG2, fg="#f0a500", font=self.FNT_S).pack(anchor="w")

        # 1. HPF
        self._hpf_en   = tk.BooleanVar(value=dsp["hpf"]["enabled"])
        self._hpf_freq = tk.DoubleVar(value=dsp["hpf"]["freq"])
        f1 = section("🔇", "Filtre Coupe-Bas (High-Pass Filter)",
                     "Coupe les ultra-graves < 40 Hz que tes baffes de bureau ne reproduisent pas."
                     " → plus de clarté, plus de punch, moins de saturation.")
        self._check_row(f1, self._hpf_en, "Activer")
        self._slider(f1, "Fréquence de coupure", self._hpf_freq, 20, 100, " Hz", res=1)

        # 2. Bass Boost
        self._bb_en   = tk.BooleanVar(value=dsp["bass_boost"]["enabled"])
        self._bb_freq = tk.DoubleVar(value=dsp["bass_boost"]["freq"])
        self._bb_gain = tk.DoubleVar(value=dsp["bass_boost"]["gain_db"])
        f2 = section("🔊", "Bass Boost — Low-Shelf (60–90 Hz)",
                     "Renforce les basses. Pré-gain de compensation automatique (évite le clipping)."
                     " Montez le bouton physique de vos baffes plutôt que le gain numérique.")
        self._check_row(f2, self._bb_en, "Activer")
        self._slider(f2, "Fréquence de coupure", self._bb_freq, 40, 200, " Hz", res=1)
        self._slider(f2, "Gain",                 self._bb_gain, 0,  12,  " dB", fmt="{:.1f}")

        # 3. Présence
        self._pr_en   = tk.BooleanVar(value=dsp["presence"]["enabled"])
        self._pr_freq = tk.DoubleVar(value=dsp["presence"]["freq"])
        self._pr_gain = tk.DoubleVar(value=dsp["presence"]["gain_db"])
        f3 = section("🗣", "Clarté Vocale — Présence (2.5–4 kHz)",
                     "+2 à +3 dB autour de 2.5–4 kHz. Les voix passent au premier plan."
                     " Tu entends les chuchotements sans monter le volume.")
        self._check_row(f3, self._pr_en, "Activer")
        self._slider(f3, "Fréquence centrale", self._pr_freq, 1000, 6000, " Hz", res=50)
        self._slider(f3, "Gain",               self._pr_gain, 0,    6,    " dB", fmt="{:.1f}")

        # 4. Compressor
        self._co_en  = tk.BooleanVar(value=dsp["compressor"]["enabled"])
        self._co_thr = tk.DoubleVar(value=dsp["compressor"]["threshold_db"])
        self._co_rat = tk.DoubleVar(value=dsp["compressor"]["ratio"])
        self._co_atk = tk.DoubleVar(value=dsp["compressor"]["attack_ms"])
        self._co_rel = tk.DoubleVar(value=dsp["compressor"]["release_ms"])
        self._co_mk  = tk.DoubleVar(value=dsp["compressor"]["makeup_db"])
        f4 = section("🎚", "Smart Volume — Compresseur Dynamique",
                     "Réduit l'écart entre sons faibles et forts. Idéal pour YouTube / films."
                     " Feedforward RMS — zéro look-ahead — zéro latence.")
        self._check_row(f4, self._co_en, "Activer")
        self._slider(f4, "Seuil (Threshold)", self._co_thr, -60, -6,  " dB",  res=1)
        self._slider(f4, "Ratio",             self._co_rat, 1,   10,  ":1",   fmt="{:.1f}", res=0.1)
        self._slider(f4, "Attaque",           self._co_atk, 5,   200, " ms",  res=1)
        self._slider(f4, "Release",           self._co_rel, 50,  1000," ms",  res=5)
        self._slider(f4, "Makeup Gain",       self._co_mk,  0,   18,  " dB",  fmt="{:.1f}")

        # 5. AI NC — désactivé, explication
        f5 = section("🤖", "Réducteur de Souffle IA (AI Noise Cancellation)",
                     "❌  Désactivé — toute implémentation temps-réel (RNNoise, DeepFilterNet…) "
                     "ajoute ≥10 ms de latence perceptible. Directive utilisateur respectée.\n\n"
                     "✅  Alternatives sans latence : NVIDIA RTX Voice · Krisp · "
                     "SteelSeries Sonar Noise Cancellation.")

    # ── Tab : À propos ────────────────────────────────────────────────────────

    def _tab_about(self, parent: ttk.Frame) -> None:
        tk.Label(parent, text=f"⚡  {APP_NAME}",
                 bg=self.BG2, fg=self.HL, font=self.FNT_H).pack(pady=(24, 4))
        tk.Label(parent, text=f"Version {VERSION}  ·  AizenOS / Antigravity",
                 bg=self.BG2, fg=self.FG2, font=self.FNT).pack()

        info = (
            "\nModes de ciblage\n"
            "  Primary → sortie Windows par défaut\n"
            "  All     → toutes les sorties actives (SteelSeries Sonar, etc.)\n"
            "  Digital → SPDIF / HDMI / Optical uniquement\n"
            "  Analog  → Bluetooth / Jack (WZ-BT5.0)\n"
            "  Marked  → sorties dont le nom contient  !\n\n"
            "Modes veille\n"
            "  SleepD  → pause si écran éteint\n"
            "  SleepL  → pause si session verrouillée\n"
            "  Sleepy  → combiné SleepD + SleepL\n\n"
            "DSP — filtres IIR biquad (Audio EQ Cookbook, RBJ)\n"
            "Zéro latence ajoutée. Buffer pré-calculé, callback temps-réel.\n\n"
            "Config stockée dans :\n"
            "%APPDATA%\\AizenSoundKeeper\\config.json"
        )
        tk.Label(parent, text=info, bg=self.BG2, fg=self.FG,
                 font=self.FNT_C, justify="left").pack(padx=20, anchor="w")

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _apply(self) -> None:
        self.cfg["device_mode"]    = self._mode_var.get()
        self.cfg["manual_devices"] = [i for i, v in self._manual_vars.items() if v.get()]
        self.cfg["amplitude_db"]   = self._amp_var.get()
        self.cfg["sleep_mode"]     = self._sleep_var.get()
        dsp = self.cfg["dsp"]
        dsp["enabled"]             = self._dsp_en.get()
        dsp["hpf"]      = {"enabled": self._hpf_en.get(), "freq": self._hpf_freq.get(), "q": 0.707}
        dsp["bass_boost"] = {
            "enabled": self._bb_en.get(), "freq": self._bb_freq.get(),
            "gain_db": self._bb_gain.get(), "q": 0.707,
        }
        dsp["presence"] = {
            "enabled": self._pr_en.get(), "freq": self._pr_freq.get(),
            "gain_db": self._pr_gain.get(), "q": 1.5,
        }
        dsp["compressor"] = {
            "enabled": self._co_en.get(),
            "threshold_db": self._co_thr.get(), "ratio": self._co_rat.get(),
            "attack_ms": self._co_atk.get(),    "release_ms": self._co_rel.get(),
            "makeup_db": self._co_mk.get(),
        }
        save_config(self.cfg)
        try:
            self.on_apply(self.cfg)
            self._status.config(text="✅ Appliqué")
            if self._win:
                self._win.after(2000, lambda: self._status.config(text=""))
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Erreur : {e}", parent=self._win)


# ══════════════════════════════════════════════════════════════════════════════
#  TRAY ICON
# ══════════════════════════════════════════════════════════════════════════════

def _make_icon(active: bool) -> "Image.Image":
    ico_file = get_resource_path("aizensoundkeeper.ico")
    if ico_file.exists():
        try:
            base_img = Image.open(str(ico_file)).convert("RGBA")
            base_img = base_img.resize((64, 64), Image.LANCZOS)
            if not active:
                gray = base_img.convert("L").convert("RGBA")
                return Image.blend(gray, Image.new("RGBA", (64, 64), (30, 30, 30, 255)), 0.45)
            return base_img
        except Exception as e:
            log.warning("Erreur chargement icone: %s", e)
    sz  = 64
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    col = "#00C853" if active else "#424242"
    d.ellipse([2, 2, sz-2, sz-2], fill=col)
    for i, h in enumerate([26, 42, 32]):
        x = 13 + i*14; y = (sz - h) // 2
        d.rectangle([x, y, x+9, y+h], fill="#FFFFFF")
    return img


def build_tray(engine: AudioEngine, sleep_mon: SleepMonitor,
               settings: SettingsWindow) -> "pystray.Icon":

    def _toggle(*_):
        if engine.active:
            engine.stop()
        else:
            engine.start()
        _refresh()

    def _refresh():
        icon.icon  = _make_icon(engine.active)
        icon.title = f"{APP_NAME}  —  {'Actif ✅' if engine.active else 'Pause ⏸'}"

    def _open_settings(*_):
        settings._root.after(0, settings.show)   # main thread safe

    def _quit(*_):
        engine.stop()
        sleep_mon.stop()
        icon.stop()
        settings._root.after(0, settings._root.quit)

    icon = pystray.Icon(
        APP_NAME,
        icon=_make_icon(True),
        title=f"{APP_NAME}  —  Actif ✅",
        menu=pystray.Menu(
            TrayItem(f"⚡  {APP_NAME}  {VERSION}", lambda *_: None, enabled=False),
            pystray.Menu.SEPARATOR,
            TrayItem("▶ / ⏸   Démarrer / Pause",  _toggle),
            TrayItem("⚙   Paramètres…",             _open_settings, default=True),
            pystray.Menu.SEPARATOR,
            TrayItem("❌  Quitter",                  _quit),
        ),
    )
    return icon


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    cfg = load_config()

    engine    = AudioEngine(cfg)
    sleep_mon = SleepMonitor(
        on_sleep=engine.stop,
        on_wake=engine.start,
        mode=cfg.get("sleep_mode", "Off"),
    )

    def on_apply(new_cfg: dict) -> None:
        sleep_mon.mode = new_cfg.get("sleep_mode", "Off")
        engine.update_config(new_cfg)

    if not HAS_TRAY:
        # Fallback console
        engine.start(); sleep_mon.start()
        print(f"\n{APP_NAME} {VERSION}  —  Ctrl+C pour arrêter.\n")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            engine.stop(); sleep_mon.stop()
        return

    # ── tkinter owns the main thread ──────────────────────────────────────────
    root = tk.Tk()
    root.withdraw()
    root.title(APP_NAME)

    settings = SettingsWindow(cfg, on_apply)
    settings.set_root(root)

    # pystray dans un thread daemon
    icon = build_tray(engine, sleep_mon, settings)
    threading.Thread(target=icon.run, daemon=True, name="Tray").start()

    # Démarrage immédiat
    engine.start()
    sleep_mon.start()

    log.info("%s %s — icône dans la zone de notification.", APP_NAME, VERSION)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        sleep_mon.stop()
        try: icon.stop()
        except Exception: pass


if __name__ == "__main__":
    main()
