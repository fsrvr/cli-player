#!/usr/bin/env python3
"""
cli_player.py — A terminal MP3 player with a cava visualizer.

Dependencies:
    sudo pacman -S vlc cava
    pip install python-vlc mutagen --break-system-packages

Usage:
    python3 cli_player.py [MUSIC_DIR]      (default ~/Documents/music)

Keybindings:
    space play/pause | Up/Down volume | Left/Right seek 5s
    n/p song | ]/[ playlist | l loop | r shuffle | q quit
    j/k browse list | enter play selected | / search | t theme
"""

import curses
import json
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlparse

os.environ.setdefault("ESCDELAY", "25")

try:
    import vlc
except ImportError:
    print("Missing dependency: python-vlc")
    print("Install with: pip install python-vlc --break-system-packages")
    print("Also make sure VLC itself is installed: sudo pacman -S vlc")
    sys.exit(1)

try:
    from mutagen import File as MutagenFile
    HAVE_MUTAGEN = True
except ImportError:
    HAVE_MUTAGEN = False

import cp_dl
import cp_fm

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus", ".wma"}
LOOP_MODES = ["off", "song", "playlist"]
BLOCKS = " ▁▂▃▄▅▆▇█"
STATE_FILE = Path.home() / ".config" / "cli-player" / "state.json"
PLAYLIST_DIR = Path.home() / ".config" / "cli-player" / "playlists"
MUSIC_DIR = Path.home() / "Documents" / "music"

# name, color (used for accent, progress bar and visualizer)
THEMES = [
    ("mono", -1),
    ("cyan", curses.COLOR_CYAN),
    ("ocean", curses.COLOR_BLUE),
    ("sunset", curses.COLOR_YELLOW),
    ("forest", curses.COLOR_GREEN),
    ("purple", curses.COLOR_MAGENTA),
    ("red", curses.COLOR_RED),
]
ACC = 0
VIZ = 0


def apply_theme(idx):
    global ACC, VIZ
    _, c = THEMES[idx]
    try:
        curses.init_pair(1, c, -1)
        ACC = VIZ = curses.color_pair(1)
    except curses.error:
        ACC = VIZ = 0


# --------------------------------------------------------------------------
# Saved state
# --------------------------------------------------------------------------

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(player, ui):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "volume": player.volume,
            "loop": player.loop_mode,
            "shuffle": player.shuffle,
            "playlist": player.playlist.name,
            "song": str(player.song.path),
            "theme": ui.theme,
            "gui": ui.gui,
        }))
    except Exception:
        pass


# --------------------------------------------------------------------------
# Visualizer (runs cava and reads its raw ascii output)
# --------------------------------------------------------------------------

class Visualizer:
    def __init__(self, bars=60):
        self.bars = bars
        self.values = [0] * bars
        self.proc = None
        self.cfg = None
        self.available = shutil.which("cava") is not None
        if self.available:
            self._start()

    def _start(self):
        cfg = (
            "[general]\n"
            f"bars = {self.bars}\n"
            "framerate = 60\n"
            "sensitivity = 110\n"
            "[smoothing]\n"
            "noise_reduction = 65\n"
            "[input]\n"
            "method = pulse\n"
            "source = auto\n"
            "[output]\n"
            "method = raw\n"
            "raw_target = /dev/stdout\n"
            "data_format = ascii\n"
            "ascii_max_range = 100\n"
            "bar_delimiter = 59\n"
            "frame_delimiter = 10\n"
        )
        fd, self.cfg = tempfile.mkstemp(suffix=".cava")
        with os.fdopen(fd, "w") as f:
            f.write(cfg)
        self.proc = subprocess.Popen(
            ["cava", "-p", self.cfg],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            try:
                vals = [int(x) for x in line.strip().split(";") if x]
            except ValueError:
                continue
            if vals:
                old = self.values
                if len(old) != len(vals):
                    old = [0] * len(vals)
                self.values = [
                    o + (v - o) * (0.5 if v > o else 0.15)
                    for o, v in zip(old, vals)
                ]

    def stop(self):
        if self.proc:
            self.proc.terminate()
        if self.cfg and os.path.exists(self.cfg):
            os.remove(self.cfg)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

def load_lrc(path):
    try:
        text = path.with_suffix(".lrc").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw)
        if not stamps:
            continue
        txt = re.sub(r"\[[^\]]*\]", "", raw).strip()
        for m, sec in stamps:
            out.append((int((int(m) * 60 + float(sec)) * 1000), txt))
    out.sort()
    return out


def current_lyric(song, cur):
    line = ""
    for t, txt in song.lyrics:
        if t <= cur:
            line = txt
        else:
            break
    return line


class Song:
    def __init__(self, path: Path):
        self.path = path
        self.title = self._read_title()
        self._lyrics = None

    @property
    def lyrics(self):
        if self._lyrics is None:
            self._lyrics = load_lrc(self.path)
        return self._lyrics

    def _read_title(self) -> str:
        if HAVE_MUTAGEN:
            try:
                tags = MutagenFile(self.path, easy=True)
                if tags and tags.get("title"):
                    artist = tags.get("artist", [""])[0]
                    title = tags["title"][0]
                    return f"{artist} - {title}" if artist else title
            except Exception:
                pass
        return self.path.stem


class Playlist:
    def __init__(self, name: str, songs, folder=None):
        self.name = name
        self.songs = songs
        self.folder = folder


def load_library(music_dir: Path):
    playlists = []
    subdirs = sorted([d for d in music_dir.iterdir() if d.is_dir()])

    def collect(folder: Path):
        files = sorted(
            f for f in folder.iterdir()
            if f.is_file() and (f.suffix.lower() in AUDIO_EXTS or f.suffix == "")
        )
        return [Song(f) for f in files]

    if subdirs:
        for d in subdirs:
            songs = collect(d)
            if songs:
                playlists.append(Playlist(d.name, songs, d))
    loose = collect(music_dir)
    if loose:
        playlists.insert(0, Playlist("All (root)", loose, music_dir))

    playlists += m3u_playlists()
    return playlists


# --------------------------------------------------------------------------
# Player engine
# --------------------------------------------------------------------------

def m3u_playlists():
    out = []
    for f in sorted(PLAYLIST_DIR.glob("*.m3u")):
        songs = [Song(Path(l)) for l in cp_fm.read_pl(f) if Path(l).is_file()]
        if songs:
            out.append(Playlist("♪ " + f.stem, songs, None))
    return out


def refresh_m3u(player):
    cur_name, cur_path = player.playlist.name, str(player.song.path)
    keep = [p for p in player.playlists if p.folder is not None]
    player.playlists = keep + m3u_playlists()
    player.queue = [(a, b) for a, b in player.queue if a < len(keep)]
    for i, p in enumerate(player.playlists):
        if p.name == cur_name:
            player.pl_idx = i
            for j, s in enumerate(p.songs):
                if str(s.path) == cur_path:
                    player.song_idx = j
            break
    else:
        player.pl_idx = player.song_idx = 0
        player._load_current(autoplay=False)
    player.song_idx = min(player.song_idx, len(player.playlist.songs) - 1)


def play_path(player, path):
    p = Path(path)
    order = sorted(range(len(player.playlists)), key=lambda i: player.playlists[i].folder is None)
    for i in order:
        for j, s in enumerate(player.playlists[i].songs):
            if s.path == p:
                player.pl_idx = i
                player.play_song(j)
                return True
    return False


def add_song(player, folder, path):
    cur = player.song
    for pl in player.playlists:
        if pl.folder == folder:
            if all(s.path != path for s in pl.songs):
                pl.songs.append(Song(path))
            pl.songs.sort(key=lambda s: s.path)
            player.song_idx = player.playlist.songs.index(cur)
            return
    player.playlists.insert(0, Playlist("All (root)", [Song(path)], folder))
    player.pl_idx += 1
    player.queue = [(a + 1, b) for a, b in player.queue]


_LEN = {}


def song_len(song):
    p = song.path
    if p not in _LEN:
        t = "--:--"
        if HAVE_MUTAGEN:
            try:
                f = MutagenFile(p)
                if f and f.info:
                    t = fmt_time(int(f.info.length * 1000))
            except Exception:
                pass
        _LEN[p] = t
    return _LEN[p]


class Player:
    def __init__(self, playlists, state=None):
        st = state or {}
        self.playlists = playlists
        self.pl_idx = 0
        self.song_idx = 0
        for i, p in enumerate(playlists):
            if p.name == st.get("playlist"):
                self.pl_idx = i
                for j, s in enumerate(p.songs):
                    if str(s.path) == st.get("song"):
                        self.song_idx = j
        loop = st.get("loop", "off")
        self.loop_mode = loop if loop in LOOP_MODES else "off"
        self.shuffle = bool(st.get("shuffle", False))
        try:
            self.volume = max(0, min(100, int(st.get("volume", 70))))
        except (TypeError, ValueError):
            self.volume = 70
        self.instance = vlc.Instance("--quiet")
        self.mp = self.instance.media_player_new()
        self.mp.audio_set_volume(self.volume)
        self.paused = False
        self.queue = []
        self.rate = 1.0
        self._rate_dirty = False
        self._rate_t = 0.0
        self._load_current(autoplay=False)

    @property
    def playlist(self):
        return self.playlists[self.pl_idx]

    @property
    def song(self):
        return self.playlist.songs[self.song_idx]

    def _load_current(self, autoplay=True):
        media = self.instance.media_new(str(self.song.path))
        self.mp.set_media(media)
        self.mp.set_rate(self.rate)
        if autoplay:
            self.mp.play()
            self.mp.set_rate(self.rate)
            self.paused = False

    def play_pause(self):
        state = self.mp.get_state()
        if state == vlc.State.Playing:
            self.mp.pause()
            self.paused = True
        else:
            self.mp.play()
            self.paused = False

    def play_song(self, idx):
        self.song_idx = idx
        self._load_current(autoplay=True)

    def next_song(self, user_initiated=True):
        if self.queue:
            self.pl_idx, self.song_idx = self.queue.pop(0)
            self._load_current(autoplay=True)
            return
        n = len(self.playlist.songs)
        if self.shuffle:
            if n > 1:
                new_idx = self.song_idx
                while new_idx == self.song_idx:
                    new_idx = random.randrange(n)
                self.song_idx = new_idx
            else:
                self.song_idx = 0
        else:
            if self.song_idx + 1 < n:
                self.song_idx += 1
            else:
                if self.loop_mode == "playlist" or user_initiated:
                    self.song_idx = 0
                else:
                    return
        self._load_current(autoplay=True)

    def prev_song(self):
        n = len(self.playlist.songs)
        if self.song_idx - 1 >= 0:
            self.song_idx -= 1
        else:
            self.song_idx = n - 1
        self._load_current(autoplay=True)

    def next_playlist(self):
        self.pl_idx = (self.pl_idx + 1) % len(self.playlists)
        self.song_idx = 0
        self._load_current(autoplay=True)

    def prev_playlist(self):
        self.pl_idx = (self.pl_idx - 1) % len(self.playlists)
        self.song_idx = 0
        self._load_current(autoplay=True)

    def seek(self, delta_sec):
        length = self.mp.get_length()
        cur = self.mp.get_time()
        if cur < 0:
            return
        new_time = max(0, cur + delta_sec * 1000)
        if length > 0:
            new_time = min(new_time, length - 500)
        self.mp.set_time(int(new_time))

    def change_volume(self, delta):
        self.volume = max(0, min(100, self.volume + delta))
        self.mp.audio_set_volume(self.volume)

    def change_speed(self, delta):
        self.rate = max(0.5, min(2.0, round(self.rate + delta, 2)))
        self._rate_t = time.time()
        self._rate_dirty = True

    def apply_rate(self):
        if self._rate_dirty and time.time() - self._rate_t > 0.15:
            self._rate_dirty = False
            self.mp.set_rate(self.rate)

    def cycle_loop(self):
        i = LOOP_MODES.index(self.loop_mode)
        self.loop_mode = LOOP_MODES[(i + 1) % len(LOOP_MODES)]

    def toggle_shuffle(self):
        self.shuffle = not self.shuffle

    def tick(self):
        state = self.mp.get_state()
        if state == vlc.State.Ended:
            if self.loop_mode == "song":
                self._load_current(autoplay=True)
            else:
                self.next_song(user_initiated=False)


# --------------------------------------------------------------------------
# UI state + helpers
# --------------------------------------------------------------------------

class UI:
    def __init__(self, theme=0):
        self.theme = theme
        self.sel = 0
        self.query = ""
        self.search_mode = False
        self.show_help = False
        self.pending = []
        self.pick = 0
        self.last_key = None
        self.bar = None
        self.rows = {}
        self.gui = "aud"
        self.btns = []
        self.prompt = None
        self.job = None
        self.job_seen = ""
        self.job_dest = None


def visible_songs(player, ui):
    songs = player.playlist.songs
    q = ui.query.lower()
    if not q:
        return list(range(len(songs)))
    return [i for i, s in enumerate(songs) if q in s.title.lower()]


def fmt_time(ms):
    if ms is None or ms < 0:
        return "--:--"
    s = ms // 1000
    m, s = divmod(s, 60)
    return f"{m:02d}:{s:02d}"


def draw_bar(width, fraction):
    fraction = max(0.0, min(1.0, fraction))
    filled = int(width * fraction)
    return "█" * filled + "─" * (width - filled)


def draw_viz(stdscr, viz: Visualizer, top, height, w):
    if height < 1:
        return
    cols = max(1, (w - 4) // 2)
    vals = viz.values
    n = len(vals)
    for r in range(height):  # r = 0 is the top row
        level_row = height - 1 - r
        line = ""
        for c in range(cols):
            v = vals[min(n - 1, c * n // cols)]
            eighths = int(min(1.0, (v / 100) ** 0.8 * 1.1) * height * 8)
            lvl = eighths - level_row * 8
            ch = BLOCKS[8] if lvl >= 8 else BLOCKS[max(0, lvl)]
            line += ch + " "
        try:
            stdscr.addstr(top + r, 2, line[:w - 4], VIZ)
        except curses.error:
            pass


def draw(stdscr, player: Player, viz: Visualizer, ui: UI, status_msg: str):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    compact = h < 15

    length = player.mp.get_length()
    cur = player.mp.get_time()
    if cur is None or cur < 0:
        cur = 0
    if length is None or length <= 0:
        length = 0
    remaining = max(0, length - cur) if length else 0
    playing = player.mp.get_state() == vlc.State.Playing

    if compact:
        r_pl, r_song, r_stat, r_bar, r_time, r_list = 1, 2, 3, 4, 5, 6
        viz_h = 0
        viz_top = h - 2
    else:
        r_pl, r_song, r_stat, r_bar, r_time, r_list = 2, 3, 5, 7, 8, 10
        viz_h = min(10, max(0, h - 14) // 2) if viz.available else 0
        viz_top = h - 3 - viz_h

    title = " CLI MP3 PLAYER "
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_REVERSE | ACC)
    stdscr.addstr(0, max(0, w - 12), "by fsrvr", curses.A_DIM)
    if not compact:
        sub = '"choose peace"'
        stdscr.addstr(1, max(0, (w - len(sub)) // 2), sub, ui.faint)
    tx = (w - len(title)) // 2
    for link in ("github.com/fsrvr/cli-player", "fsrvr/cli-player"):
        if 2 + len(link) < tx:
            stdscr.addstr(0, 2, link, curses.A_DIM)
            break
    stdscr.addstr(r_pl, 2, (f"Playlist: {player.playlist.name} "
                            f"({player.pl_idx + 1}/{len(player.playlists)})")[:w - 4])
    stdscr.addstr(r_song, 2, (f"Song:     {player.song.title} "
                              f"({player.song_idx + 1}/{len(player.playlist.songs)})")[:w - 4],
                  ACC | curses.A_BOLD)
    status = "PLAYING" if playing else "PAUSED"
    stdscr.addstr(r_stat, 2, (f"Status: {status}   Loop: {player.loop_mode}   "
                              f"Shuffle: {'on' if player.shuffle else 'off'}   "
                              f"Vol: {player.volume}%   Speed: {player.rate:.1f}x")[:w - 4])
    frac = (cur / length) if length else 0
    stdscr.addstr(r_bar, 2, draw_bar(max(10, w - 20), frac)[:w - 4], ACC)
    ui.bar = (r_bar, 2, min(max(10, w - 20), w - 4))
    if not compact:
        lyr = current_lyric(player.song, cur)
        if lyr:
            stdscr.addstr(6, 2, lyr[:w - 4], ACC)
    stdscr.addstr(r_time, 2, (f"{fmt_time(cur)} elapsed   {fmt_time(length)} total   "
                              f"-{fmt_time(remaining)} remaining")[:w - 4])
    if player.queue and not compact:
        qpl, qsi = player.queue[0]
        more = f"  +{len(player.queue) - 1} more" if len(player.queue) > 1 else ""
        stdscr.addstr(9, 2, f"Next up: {player.playlists[qpl].songs[qsi].title}{more}"[:w - 4], ACC)

    # song list (scrolling, cursor, search filter)
    songs = player.playlist.songs
    vis = visible_songs(player, ui)
    ui.sel = max(0, min(ui.sel, len(vis) - 1)) if vis else 0
    ui.rows = {}
    row = r_list
    if not compact:
        header = f"Matches ({len(vis)}):" if ui.query else "Songs:"
        stdscr.addstr(r_list, 2, header, ACC)
        row += 1
    avail = viz_top - row
    if avail > 0:
        if not vis:
            stdscr.addstr(row, 4, "no matches", curses.A_DIM)
        else:
            off = max(0, min(ui.sel - avail // 2, len(vis) - avail))
            for k in range(off, min(len(vis), off + avail)):
                i = vis[k]
                is_cur = i == player.song_idx
                marker = "▶ " if is_cur else "  "
                attr = (ACC | curses.A_BOLD) if is_cur else curses.A_NORMAL
                if k == ui.sel:
                    attr |= curses.A_REVERSE
                qn = [n for n, (pi, si) in enumerate(player.queue, 1)
                      if pi == player.pl_idx and si == i]
                tag = f"[q{qn[0]}] " if qn else ""
                ui.rows[row] = k
                stdscr.addstr(row, 4, f"{marker}{i + 1:>2}. {tag}{songs[i].title}"[:w - 6], attr)
                row += 1

    draw_viz(stdscr, viz, viz_top, viz_h, w)

    if ui.pending:
        n = len(ui.pending)
        help_line = ui.pending[0].name + (f"  +{n - 1} more" if n > 1 else "")
        status_msg = "↑/↓:select  enter:confirm  esc:cancel"
    elif ui.search_mode:
        help_line = "type to filter   up/down:select   enter:play   esc:cancel"
        status_msg = f"/{ui.query}_"
    else:
        help_line = ("h:help spc:pause ←→:seek ↑↓:vol n/p:song "
                     "]/[:list l:loop r:shuf")
    stdscr.addstr(h - 2, 2, help_line[:w - 4], curses.A_DIM)
    if status_msg:
        stdscr.addstr(h - 1, 2, status_msg[:w - 4], ACC if (ui.search_mode or ui.pending) else curses.A_DIM)

    if ui.pending:
        bw = min(w - 4, max(24, len(player.playlist.name) + 14))
        inner = bw - 2
        y0 = max(0, (h - 5) // 2)
        x0 = max(0, (w - bw) // 2)

        def put(y, text, attr=curses.A_NORMAL):
            try:
                stdscr.addstr(y, x0, text, attr)
            except curses.error:
                pass

        t = f" add to {player.playlist.name} "[:inner]
        put(y0, "┌" + t.center(inner, "─") + "┐", ACC)
        for k, label in enumerate(("copy", "move")):
            sel = (curses.A_REVERSE | ACC) if ui.pick == k else curses.A_NORMAL
            put(y0 + 1 + k * 2, "│" + label.center(inner) + "│", sel)
        put(y0 + 2, "│" + "─" * inner + "│")
        put(y0 + 4, "└" + "─" * inner + "┘", ACC)
    stdscr.refresh()


def draw_pending(stdscr, player, ui, h, w):
    bw = min(w - 4, max(24, len(player.playlist.name) + 14))
    inner = bw - 2
    y0 = max(0, (h - 5) // 2)
    x0 = max(0, (w - bw) // 2)

    def put(y, text, attr=curses.A_NORMAL):
        try:
            stdscr.addstr(y, x0, text, attr)
        except curses.error:
            pass

    t = f" add to {player.playlist.name} "[:inner]
    put(y0, "┌" + t.center(inner, "─") + "┐", ACC)
    for k, label in enumerate(("copy", "move")):
        s = (curses.A_REVERSE | ACC) if ui.pick == k else curses.A_NORMAL
        put(y0 + 1 + k * 2, "│" + label.center(inner) + "│", s)
    put(y0 + 2, "│" + "─" * inner + "│")
    put(y0 + 4, "└" + "─" * inner + "┘", ACC)


def draw_aud(stdscr, player, viz, ui, status_msg):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    iw = w - 4
    length = max(0, player.mp.get_length() or 0)
    cur = max(0, player.mp.get_time() or 0)
    playing = player.mp.get_state() == vlc.State.Playing
    ui.btns, ui.rows = [], {}

    def put(y, x, s, a=0):
        try:
            stdscr.addstr(y, x, s[:max(0, w - x)], a)
        except curses.error:
            pass

    for y in range(1, h - 2):
        put(y, 0, "│")
        put(y, w - 1, "│")
    put(0, 0, "┌" + " cli-player ".center(w - 2, "─") + "┐", ACC)
    put(h - 2, 0, "└" + "─" * (w - 2) + "┘", ACC)
    if ui.job and not ui.job.done:
        put(0, 2, " downloading ", ACC | curses.A_BOLD)

    head = f"{'▶' if playing else '❚❚'} {fmt_time(cur)}"
    put(1, 2, head, ACC | curses.A_BOLD)
    x = 2 + len(head) + 2
    if viz.available:
        n = len(viz.values)
        vz = "".join(BLOCKS[max(0, min(8, int(viz.values[c * n // 16] / 100 * 9)))] for c in range(16))
        put(1, x, vz, VIZ)
        x += 18
    t = player.song.title
    tw = max(1, w - 2 - x)
    if len(t) > tw:
        s = t + "   ***   "
        o = int(time.time() * 4) % len(s)
        t = (s + s)[o:o + tw]
    put(1, x, t, ACC | curses.A_BOLD)

    vb = 10
    f = player.volume * vb // 100
    put(2, 2, (f"vol {'█' * f}{'░' * (vb - f)} {player.volume:>3}%   speed {player.rate:.1f}x   "
               f"loop:{player.loop_mode}   shuffle:{'on' if player.shuffle else 'off'}")[:iw])

    bw = max(10, iw - 12)
    put(3, 2, draw_bar(bw, cur / length if length else 0), ACC)
    put(3, 3 + bw, f"{fmt_time(cur)}/{fmt_time(length)}")
    ui.bar = (3, 2, bw)

    x = 2
    for label, key, on in (("[|<]", ord('p'), 0), ("[>||]", ord(' '), 0), ("[■]", ord('s'), 0),
                           ("[>|]", ord('n'), 0), (None, 0, 0),
                           ("[shuf]", ord('r'), player.shuffle),
                           ("[loop]", ord('l'), player.loop_mode != "off"), (None, 0, 0),
                           ("[files]", ord('f'), 0), ("[dl]", ord('d'), 0), ("[legacy]", ord('g'), 0)):
        if label is None:
            x += 2
            continue
        put(4, x, label, (ACC | curses.A_REVERSE) if on else 0)
        ui.btns.append((4, x, x + len(label), key))
        x += len(label) + 1

    lyr = current_lyric(player.song, cur)
    if lyr:
        put(5, 2, lyr[:iw], ACC)
    elif player.queue:
        qpl, qsi = player.queue[0]
        put(5, 2, f"Next up: {player.playlists[qpl].songs[qsi].title}"[:iw], curses.A_DIM)

    put(6, 0, "├" + f" {player.playlist.name} ({player.pl_idx + 1}/{len(player.playlists)}) ".center(w - 2, "─") + "┤", ACC)
    songs = player.playlist.songs
    vis = visible_songs(player, ui)
    ui.sel = max(0, min(ui.sel, len(vis) - 1)) if vis else 0
    row, avail = 7, h - 9
    if avail > 0:
        if not vis:
            put(row, 4, "no matches", curses.A_DIM)
        else:
            off = max(0, min(ui.sel - avail // 2, len(vis) - avail))
            for k in range(off, min(len(vis), off + avail)):
                i = vis[k]
                is_cur = i == player.song_idx
                qn = [n for n, (pi, si) in enumerate(player.queue, 1)
                      if pi == player.pl_idx and si == i]
                d = song_len(songs[i])
                left = f"{'▶' if is_cur else ' '} {i + 1:>3}. {'[q%d] ' % qn[0] if qn else ''}{songs[i].title}"
                text = left[:max(0, iw - len(d) - 1)].ljust(max(0, iw - len(d))) + d
                attr = (ACC | curses.A_BOLD) if is_cur else curses.A_NORMAL
                if k == ui.sel:
                    attr |= curses.A_REVERSE
                ui.rows[row] = k
                put(row, 2, text, attr)
                row += 1
    put(h - 2, 2, f" {len(vis)} songs ", ACC)

    if ui.pending:
        foot, a = "↑/↓:select  enter:confirm  esc:cancel", ACC
    elif ui.search_mode:
        foot, a = f"/{ui.query}_", ACC
    elif status_msg:
        foot, a = status_msg, ACC
    else:
        foot, a = "h:help  g:legacy  f:files  d:download  /:search  t:theme", curses.A_DIM
    put(h - 1, 2, foot[:w - 4], a)
    if ui.pending:
        draw_pending(stdscr, player, ui, h, w)
    stdscr.refresh()


HELP = [
    ("space", "play / pause"),
    ("← / →", "seek -5s / +5s"),
    ("↑ / ↓", "volume up / down"),
    ("n / p", "next / previous song"),
    ("] / [", "next / previous playlist"),
    ("j / k", "move cursor in song list"),
    ("enter", "play selected song"),
    ("a", "add selected song to queue"),
    ("x / X", "remove from queue / clear queue"),
    (", / .", "speed -0.1x / +0.1x"),
    ("click", "bar: seek, song: play"),
    ("scroll", "volume up / down"),
    ("/", "search (esc cancels)"),
    ("l", "cycle loop: off / song / playlist"),
    ("r", "toggle shuffle"),
    ("t", "cycle color theme"),
    ("drop", "drag a file in: copy/move to playlist"),
    ("g", "switch GUI: audacious / legacy"),
    ("f", "file manager / playlists"),
    ("d", "download song+lyrics+cover"),
    ("s", "stop"),
    ("h", "show this help"),
    ("q", "quit"),
]


def draw_help(stdscr):
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    title = " KEYBINDS "
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_REVERSE | ACC)
    for i, (k, d) in enumerate(HELP):
        y = 1 + i
        if y >= h - 1:
            break
        stdscr.addstr(y, 4, f"{k:<8}", ACC | curses.A_BOLD)
        stdscr.addstr(y, 12, d[:max(0, w - 14)])
    stdscr.addstr(h - 1, 2, "press any key to close"[:w - 4], curses.A_DIM)
    stdscr.refresh()


MIN_W, MIN_H = 68, 10


def draw_safe(stdscr, player, viz, ui, status_msg):
    h, w = stdscr.getmaxyx()
    if h < MIN_H or w < MIN_W:
        stdscr.erase()
        lines = ["Terminal too small",
                 f"Width:  {w} (need {MIN_W})",
                 f"Height: {h} (need {MIN_H})"]
        for i, l in enumerate(lines):
            y = h // 2 - 1 + i
            x = max(0, (w - len(l)) // 2)
            if 0 <= y < h:
                try:
                    stdscr.addstr(y, x, l[:max(0, w - x - 1)])
                except curses.error:
                    pass
        stdscr.refresh()
        return
    try:
        if ui.show_help:
            draw_help(stdscr)
        else:
            (draw_aud if ui.gui == "aud" else draw)(stdscr, player, viz, ui, status_msg)
    except curses.error:
        pass


def parse_drop(chars):
    """Turn a burst of typed chars into audio file paths (drag & drop)."""
    if len(chars) < 4 or any(c < 0 or c > 255 for c in chars):
        return []
    text = bytes(chars).decode("utf-8", "ignore")
    for mark in ("\x1b[200~", "\x1b[201~"):
        text = text.replace(mark, "")
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return []

    def to_path(part):
        if part.startswith("file://"):
            part = unquote(urlparse(part).path)
        return Path(part).expanduser()

    try:
        parts = shlex.split(text)
    except ValueError:
        parts = [text]
    files = [p for p in map(to_path, parts)
             if p.is_file() and (p.suffix.lower() in AUDIO_EXTS or p.suffix == "")]
    if not files:
        p = to_path(text)
        if p.is_file() and (p.suffix.lower() in AUDIO_EXTS or p.suffix == ""):
            files = [p]
    return files


def import_files(player, files, move):
    folder = player.playlist.folder
    if folder is None:
        return 0
    cur = player.song
    done = 0
    for src in files:
        dest = folder / src.name
        if dest.exists():
            if dest.resolve() == src.resolve():
                continue
            n = 1
            while dest.exists():
                dest = folder / f"{src.stem} ({n}){src.suffix}"
                n += 1
        try:
            if move:
                shutil.move(str(src), str(dest))
            else:
                shutil.copy2(src, dest)
        except OSError:
            continue
        player.playlist.songs.append(Song(dest))
        done += 1
    player.playlist.songs.sort(key=lambda s: s.path)
    player.song_idx = player.playlist.songs.index(cur)
    return done


def is_enter(ch):
    return ch in (10, 13, curses.KEY_ENTER)


def play_selected(player, ui):
    vis = visible_songs(player, ui)
    if vis:
        player.play_song(vis[ui.sel])
    ui.query = ""
    ui.search_mode = False
    ui.sel = player.song_idx


def main(stdscr, player: Player, viz: Visualizer, ui: UI):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.use_default_colors()
    apply_theme(ui.theme)
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    curses.mouseinterval(0)
    ui.faint = curses.A_DIM
    try:
        if curses.COLORS >= 256:
            curses.init_pair(2, 236, -1)
            ui.faint = curses.color_pair(2)
    except curses.error:
        pass

    if getattr(ui, "first_run", False):
        stdscr.nodelay(False)
        opts = [("aud", "New GUI", "Audacious-style window with buttons and durations"),
                ("legacy", "Legacy GUI", "the original layout with the big visualizer")]
        pick = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            lines = [(" Choose your GUI ", curses.A_REVERSE | ACC),
                     ("(press g anytime to switch)", curses.A_DIM), ("", 0)]
            for k, (_, name, desc) in enumerate(opts):
                lines.append((f"{'>' if k == pick else ' '} {k + 1}. {name} - {desc}",
                              (curses.A_REVERSE | ACC) if k == pick else 0))
            lines += [("", 0), ("up/down + enter, or press 1 / 2", curses.A_DIM)]
            for n, (t, a) in enumerate(lines):
                y = h // 2 - len(lines) // 2 + n
                x = max(0, (w - len(t)) // 2)
                if 0 <= y < h:
                    try:
                        stdscr.addstr(y, x, t[:max(0, w - x - 1)], a)
                    except curses.error:
                        pass
            stdscr.refresh()
            c = stdscr.getch()
            if c in (curses.KEY_UP, curses.KEY_DOWN, ord('j'), ord('k'), 9):
                pick = 1 - pick
            elif c in (ord('1'), ord('2')):
                pick = c - ord('1')
                break
            elif is_enter(c) or c == 27:
                break
        ui.gui = opts[pick][0]
        ui.first_run = False
        stdscr.nodelay(True)

    player.mp.play()
    status_msg = "" if viz.available else "cava not found: sudo pacman -S cava"
    last_tick = time.time()
    msg_seen = status_msg
    msg_time = last_tick
    ui.sel = player.song_idx
    last_pl = player.pl_idx
    keyq = deque()

    def start_dl(text):
        if ui.job and not ui.job.done:
            return "Download already running"
        if not cp_dl.available():
            return "need: sudo pacman -S yt-dlp ffmpeg"
        ui.job_dest = player.playlist.folder or MUSIC_DIR
        ui.job = cp_dl.Job(text, ui.job_dest)
        return "Downloading..."

    while True:
        chars = []
        while True:
            got = False
            while len(chars) < 4096:
                try:
                    c = stdscr.getch()
                except curses.error:
                    c = -1
                if c == -1:
                    break
                chars.append(c)
                got = True
            if not got or len(chars) < 2:
                break
            time.sleep(0.02)
        if chars:
            files = parse_drop(chars) if not (ui.search_mode or ui.pending or ui.prompt) else []
            if files:
                ui.pending = files
                ui.pick = 0
            else:
                keyq.extend(chars)
        ch = keyq.popleft() if keyq else -1

        if ch != -1:
            if ui.prompt:
                p = ui.prompt
                if ch == 27:
                    ui.prompt = None
                elif is_enter(ch):
                    ui.prompt = None
                    if p["text"].strip():
                        status_msg = p["cb"](p["text"].strip()) or ""
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    p["text"] = p["text"][:-1]
                elif 32 <= ch <= 126:
                    p["text"] += chr(ch)
            elif ui.pending:
                if ch in (curses.KEY_UP, curses.KEY_DOWN, ord('j'), ord('k')):
                    ui.pick = 1 - ui.pick
                elif is_enter(ch):
                    mv = ui.pick == 1
                    n = import_files(player, ui.pending, mv)
                    status_msg = (f"{'Moved' if mv else 'Copied'} {n} file{'s' if n != 1 else ''} to {player.playlist.name}"
                                  if n else "Nothing imported")
                    ui.pending = []
                    ui.sel = player.song_idx
                elif ch == 27:
                    ui.pending = []
                    status_msg = "Import cancelled"
            elif ui.show_help:
                ui.show_help = False
            elif ui.search_mode:
                if ch == 27:
                    ui.search_mode = False
                    ui.query = ""
                    ui.sel = player.song_idx
                elif is_enter(ch):
                    play_selected(player, ui)
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    ui.query = ui.query[:-1]
                    ui.sel = 0
                elif ch == curses.KEY_UP:
                    ui.sel = max(0, ui.sel - 1)
                elif ch == curses.KEY_DOWN:
                    ui.sel += 1
                elif 32 <= ch <= 126:
                    ui.query += chr(ch)
                    ui.sel = 0
            elif ch in (ord('q'), ord('Q')):
                break
            elif ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bs = curses.getmouse()
                except curses.error:
                    bs = mx = my = 0
                if bs & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                    b = ui.bar
                    hit = [k for (by, x0, x1, k) in ui.btns if my == by and x0 <= mx < x1]
                    if hit:
                        keyq.append(hit[0])
                    elif b and my == b[0] and b[1] <= mx < b[1] + b[2]:
                        length = player.mp.get_length()
                        if length > 0:
                            player.mp.set_time(int(length * (mx - b[1]) / b[2]))
                    elif my in ui.rows:
                        ui.sel = ui.rows[my]
                        play_selected(player, ui)
                elif bs & curses.BUTTON4_PRESSED:
                    player.change_volume(+5)
                elif bs & getattr(curses, "BUTTON5_PRESSED", 0):
                    player.change_volume(-5)
            elif ch == ord('x'):
                vis = visible_songs(player, ui)
                if vis and (player.pl_idx, vis[ui.sel]) in player.queue:
                    player.queue.remove((player.pl_idx, vis[ui.sel]))
                    status_msg = f"Removed from queue: {len(player.queue)} left"
            elif ch == ord('X'):
                player.queue.clear()
                status_msg = "Queue cleared"
            elif ch == ord(','):
                player.change_speed(-0.1)
                status_msg = f"Speed: {player.rate:.1f}x"
            elif ch == ord('.'):
                player.change_speed(+0.1)
                status_msg = f"Speed: {player.rate:.1f}x"
            elif ch == ord(' '):
                player.play_pause()
            elif ch == curses.KEY_UP:
                player.change_volume(+5)
            elif ch == curses.KEY_DOWN:
                player.change_volume(-5)
            elif ch == curses.KEY_LEFT:
                player.seek(-5)
            elif ch == curses.KEY_RIGHT:
                player.seek(+5)
            elif ch in (ord('a'), ord('A')):
                vis = visible_songs(player, ui)
                if vis:
                    player.queue.append((player.pl_idx, vis[ui.sel]))
                    status_msg = f"Queued: {len(player.queue)}"
            elif ch in (ord('n'), ord('N')):
                player.next_song()
            elif ch in (ord('p'), ord('P')):
                player.prev_song()
            elif ch == ord(']'):
                player.next_playlist()
            elif ch == ord('['):
                player.prev_playlist()
            elif ch in (ord('l'), ord('L')):
                player.cycle_loop()
                status_msg = f"Loop mode: {player.loop_mode}"
            elif ch in (ord('r'), ord('R')):
                player.toggle_shuffle()
                status_msg = f"Shuffle: {'on' if player.shuffle else 'off'}"
            elif ch == ord('j'):
                ui.sel += 1
            elif ch == ord('k'):
                ui.sel = max(0, ui.sel - 1)
            elif is_enter(ch):
                play_selected(player, ui)
            elif ch == ord('/'):
                ui.search_mode = True
                ui.query = ""
                ui.sel = 0
            elif ch in (ord('h'), ord('H'), ord('?')):
                ui.show_help = True
            elif ch == ord('g'):
                ui.gui = "legacy" if ui.gui == "aud" else "aud"
                status_msg = f"GUI: {ui.gui}"
            elif ch == ord('s'):
                player.mp.stop()
                player.paused = True
            elif ch == ord('d'):
                ui.prompt = {"label": "download (url or search): ", "text": "", "cb": start_dl}
            elif ch == ord('f'):
                r = cp_fm.run(stdscr, MUSIC_DIR, PLAYLIST_DIR, ACC)
                refresh_m3u(player)
                if r:
                    play_path(player, r)
                ui.last_key = None
                last_pl = player.pl_idx
            elif ch in (ord('t'), ord('T')):
                ui.theme = (ui.theme + 1) % len(THEMES)
                apply_theme(ui.theme)
                status_msg = f"Theme: {THEMES[ui.theme][0]}"

        # keep cursor following the playing song / reset on playlist change
        if player.pl_idx != last_pl:
            last_pl = player.pl_idx
            ui.query = ""
            ui.search_mode = False
            ui.sel = player.song_idx
        key = (player.pl_idx, player.song_idx)
        if key != ui.last_key:
            ui.last_key = key
            if not ui.query:
                ui.sel = player.song_idx

        if ui.job:
            job = ui.job
            done = job.done
            if job.msg != ui.job_seen:
                ui.job_seen = status_msg = job.msg
            if done:
                if job.result:
                    add_song(player, ui.job_dest, job.result)
                if not job.result:
                    ui.err = (job.msg, time.time() + 10)
                ui.job = None

        now = time.time()
        if status_msg != msg_seen:
            msg_seen = status_msg
            msg_time = now
        if status_msg and now - msg_time > 3:
            status_msg = msg_seen = ""
        player.apply_rate()
        if now - last_tick > 0.4:
            player.tick()
            last_tick = now

        err = getattr(ui, "err", None)
        if ui.prompt:
            shown = f"{ui.prompt['label']}{ui.prompt['text']}_"
        elif ui.job and not ui.job.done:
            shown = "⇩ " + ui.job.msg
        elif err and time.time() < err[1]:
            shown = err[0]
        else:
            shown = status_msg
        draw_safe(stdscr, player, viz, ui, shown)
        time.sleep(0.03)


def start_notifier(player):
    if not shutil.which("notify-send"):
        return

    def loop():
        last = player.song.path
        while True:
            try:
                cur = player.song
                if cur.path != last:
                    last = cur.path
                    subprocess.Popen(
                        ["notify-send", "-a", "cli-player", "-t", "3000",
                         "Now playing", cur.title],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
            except Exception:
                pass
            time.sleep(0.5)

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    music_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Documents" / "music"
    music_dir = music_dir.resolve()
    MUSIC_DIR = music_dir
    if not music_dir.is_dir():
        print(f"Music directory not found: {music_dir}")
        sys.exit(1)

    playlists = load_library(music_dir)
    if not playlists:
        print(f"No audio files found under {music_dir}")
        print(f"Supported extensions: {', '.join(sorted(AUDIO_EXTS))}")
        sys.exit(1)

    state = load_state()
    theme = state.get("theme", 0)
    if not isinstance(theme, int) or not 0 <= theme < len(THEMES):
        theme = 0
    player = Player(playlists, state)
    start_notifier(player)
    ui = UI(theme)
    ui.first_run = state.get("gui") not in ("aud", "legacy")
    ui.gui = state.get("gui") if not ui.first_run else "aud"
    viz = Visualizer(bars=60)
    try:
        curses.wrapper(main, player, viz, ui)
    finally:
        save_state(player, ui)
        player.mp.stop()
        viz.stop()
