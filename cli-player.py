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
"""

import curses
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

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

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus", ".wma"}
LOOP_MODES = ["off", "song", "playlist"]
BLOCKS = " ▁▂▃▄▅▆▇█"


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

class Song:
    def __init__(self, path: Path):
        self.path = path
        self.title = self._read_title()

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
    def __init__(self, name: str, songs):
        self.name = name
        self.songs = songs


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
                playlists.append(Playlist(d.name, songs))
    loose = collect(music_dir)
    if loose:
        playlists.insert(0, Playlist("All (root)", loose))

    return playlists


# --------------------------------------------------------------------------
# Player engine
# --------------------------------------------------------------------------

class Player:
    def __init__(self, playlists):
        self.playlists = playlists
        self.pl_idx = 0
        self.song_idx = 0
        self.loop_mode = "off"
        self.shuffle = False
        self.volume = 70
        self.instance = vlc.Instance("--quiet")
        self.mp = self.instance.media_player_new()
        self.mp.audio_set_volume(self.volume)
        self.paused = False
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
        if autoplay:
            self.mp.play()
            self.paused = False

    def play_pause(self):
        state = self.mp.get_state()
        if state == vlc.State.Playing:
            self.mp.pause()
            self.paused = True
        else:
            self.mp.play()
            self.paused = False

    def next_song(self, user_initiated=True):
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
# UI helpers
# --------------------------------------------------------------------------

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
            stdscr.addstr(top + r, 2, line[:w - 4])
        except curses.error:
            pass


def draw(stdscr, player: Player, viz: Visualizer, status_msg: str):
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
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_REVERSE)
    stdscr.addstr(0, max(0, w - 12), "by fsrvr", curses.A_DIM)
    tx = (w - len(title)) // 2
    for link in ("github.com/fsrvr/cli-player", "fsrvr/cli-player"):
        if 2 + len(link) < tx:
            stdscr.addstr(0, 2, link, curses.A_DIM)
            break
    stdscr.addstr(r_pl, 2, (f"Playlist: {player.playlist.name} "
                            f"({player.pl_idx + 1}/{len(player.playlists)})")[:w - 4])
    stdscr.addstr(r_song, 2, (f"Song:     {player.song.title} "
                              f"({player.song_idx + 1}/{len(player.playlist.songs)})")[:w - 4])
    status = "PLAYING" if playing else "PAUSED"
    stdscr.addstr(r_stat, 2, (f"Status: {status}   Loop: {player.loop_mode}   "
                              f"Shuffle: {'on' if player.shuffle else 'off'}   "
                              f"Vol: {player.volume}%")[:w - 4])
    frac = (cur / length) if length else 0
    stdscr.addstr(r_bar, 2, draw_bar(max(10, w - 20), frac)[:w - 4])
    stdscr.addstr(r_time, 2, (f"{fmt_time(cur)} elapsed   {fmt_time(length)} total   "
                              f"-{fmt_time(remaining)} remaining")[:w - 4])

    songs = player.playlist.songs
    row = r_list
    if not compact:
        stdscr.addstr(r_list, 2, "Up next in this playlist:")
        row += 1
    start = max(0, player.song_idx - (0 if compact else 2))
    for i in range(start, len(songs)):
        if row >= viz_top:
            break
        marker = "▶ " if i == player.song_idx else "  "
        attr = curses.A_BOLD if i == player.song_idx else curses.A_NORMAL
        stdscr.addstr(row, 4, f"{marker}{i + 1:>2}. {songs[i].title}"[:w - 6], attr)
        row += 1

    draw_viz(stdscr, viz, viz_top, viz_h, w)

    help_line = ("space:play/pause  ←/→:seek5s  ↑/↓:vol  "
                 "n/p:song  ]/[:playlist  l:loop  r:shuffle  q:quit")
    stdscr.addstr(h - 2, 2, help_line[:w - 4], curses.A_DIM)
    if status_msg:
        stdscr.addstr(h - 1, 2, status_msg[:w - 4], curses.A_DIM)
    stdscr.refresh()


MIN_W, MIN_H = 60, 10


def draw_safe(stdscr, player, viz, status_msg):
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
        draw(stdscr, player, viz, status_msg)
    except curses.error:
        pass


def main(stdscr, player: Player, viz: Visualizer):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.use_default_colors()

    player.mp.play()
    status_msg = "" if viz.available else "cava not found: sudo pacman -S cava"
    last_tick = time.time()

    while True:
        try:
            ch = stdscr.getch()
        except curses.error:
            ch = -1

        if ch != -1:
            if ch in (ord('q'), ord('Q')):
                break
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

        now = time.time()
        if now - last_tick > 0.4:
            player.tick()
            last_tick = now

        draw_safe(stdscr, player, viz, status_msg)
        time.sleep(0.03)


if __name__ == "__main__":
    music_dir = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Documents" / "music"
    if not music_dir.is_dir():
        print(f"Music directory not found: {music_dir}")
        sys.exit(1)

    playlists = load_library(music_dir)
    if not playlists:
        print(f"No audio files found under {music_dir}")
        print(f"Supported extensions: {', '.join(sorted(AUDIO_EXTS))}")
        sys.exit(1)

    player = Player(playlists)
    viz = Visualizer(bars=60)
    try:
        curses.wrapper(main, player, viz)
    finally:
        player.mp.stop()
        viz.stop()
