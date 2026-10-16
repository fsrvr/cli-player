#!/usr/bin/env python3
"""
cli_player.py — A terminal MP3 player.

Playlists = subfolders of your music directory (each folder's audio files
become one playlist). Works great in any terminal under Hyprland.

Dependencies:
    sudo pacman -S vlc
    pip install python-vlc mutagen --break-system-packages

Usage:
    python3 cli_player.py [MUSIC_DIR]

    MUSIC_DIR defaults to ~/Documents/music
    Layout expected:
        ~/music/
            Chill/
                song1.mp3
                song2.mp3
            Workout/
                song3.mp3
                song4.mp3

Keybindings:
    space       play / pause
    Up / Down   volume + / -
    Left/Right  seek -5s / +5s
    n / p       next / previous song (in current playlist)
    ] / [       next / previous playlist
    l           cycle loop mode: off -> song -> playlist -> off
    r           toggle shuffle
    q           quit
"""

import curses
import os
import sys
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
    # Also include any loose files directly in music_dir as "All"
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
            import random
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
                    return  # end of playlist, nothing to do
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
        length = self.mp.get_length()  # ms, -1 if unknown
        cur = self.mp.get_time()  # ms
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
        """Call regularly to auto-advance when a song ends."""
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


def draw(stdscr, player: Player, status_msg: str):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    length = player.mp.get_length()
    cur = player.mp.get_time()
    if cur is None or cur < 0:
        cur = 0
    if length is None or length <= 0:
        length = 0

    remaining = max(0, length - cur) if length else 0
    state = player.mp.get_state()
    playing = state == vlc.State.Playing

    title = " CLI MP3 PLAYER "
    stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_REVERSE)

    stdscr.addstr(2, 2, f"Playlist: {player.playlist.name} "
                         f"({player.pl_idx + 1}/{len(player.playlists)})")
    stdscr.addstr(3, 2, f"Song:     {player.song.title} "
                         f"({player.song_idx + 1}/{len(player.playlist.songs)})")

    status = "PLAYING" if playing else "PAUSED"
    stdscr.addstr(5, 2, f"Status: {status}   "
                         f"Loop: {player.loop_mode}   "
                         f"Shuffle: {'on' if player.shuffle else 'off'}   "
                         f"Vol: {player.volume}%")

    bar_width = max(10, w - 20)
    frac = (cur / length) if length else 0
    stdscr.addstr(7, 2, draw_bar(bar_width, frac))
    stdscr.addstr(8, 2, f"{fmt_time(cur)} elapsed   "
                         f"{fmt_time(length)} total   "
                         f"-{fmt_time(remaining)} remaining")

    # Playlist track listing (scrollable window around current song)
    stdscr.addstr(10, 2, "Up next in this playlist:")
    songs = player.playlist.songs
    start = max(0, player.song_idx - 2)
    end = min(len(songs), start + max(1, h - 14))
    row = 11
    for i in range(start, end):
        marker = "▶ " if i == player.song_idx else "  "
        line = f"{marker}{i + 1:>2}. {songs[i].title}"
        attr = curses.A_BOLD if i == player.song_idx else curses.A_NORMAL
        if row < h - 3:
            stdscr.addstr(row, 4, line[:w - 6], attr)
            row += 1

    help_line = ("space:play/pause  ←/→:seek5s  ↑/↓:vol  "
                 "n/p:song  ]/[:playlist  l:loop  r:shuffle  q:quit")
    stdscr.addstr(h - 2, 2, help_line[:w - 4], curses.A_DIM)
    if status_msg:
        stdscr.addstr(h - 1, 2, status_msg[:w - 4], curses.A_DIM)

    stdscr.refresh()


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def main(stdscr, player: Player):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.use_default_colors()

    player.mp.play()
    status_msg = ""
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

        # Auto-advance on song end
        now = time.time()
        if now - last_tick > 0.4:
            player.tick()
            last_tick = now

        draw(stdscr, player, status_msg)
        time.sleep(0.05)


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
    try:
        curses.wrapper(main, player)
    finally:
        player.mp.stop()
