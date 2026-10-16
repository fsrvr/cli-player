# cli-player

A lightweight terminal MP3 player built with Python, curses, and VLC. Folders become playlists, with shuffle, loop, seek, volume controls, and a cava visualizer.

## Installation

**Compatible systems:** Arch Linux, Debian/Ubuntu, macOS

**Arch**
```bash
sudo pacman -S vlc cava python-pip
pip install -r requirements.txt --break-system-packages
```

**Debian / Ubuntu**
```bash
sudo apt install vlc cava python3-pip
pip install -r requirements.txt --break-system-packages
```

**macOS**
```bash
brew install --cask vlc
brew install cava
pip install -r requirements.txt
```

## Run

```bash
python3 cli-player.py [MUSIC_DIR]   # default: ~/Documents/music
```

> macOS: cava needs a loopback device (e.g. BlackHole) to capture audio, so the visualizer may stay flat.
> Flat on Linux? Change `method = pulse` to `method = pipewire` in the cava config inside `cli-player.py`.

## Folder layout

```
~/Documents/music/
    Chill/
        song1.mp3
    Workout/
        song2.mp3
```

## Controls

| Key | Action |
|-----|--------|
| `Space` | Play / pause |
| `↑` / `↓` | Volume up / down |
| `←` / `→` | Seek -5s / +5s |
| `n` / `p` | Next / previous song |
| `]` / `[` | Next / previous playlist |
| `l` | Cycle loop mode (off, song, playlist) |
| `r` | Toggle shuffle |
| `q` | Quit |

## Notes

- Minimum terminal size: 60x10. Below 15 rows it switches to a compact layout, and the visualizer appears from about 16 rows up.
- If the terminal is too small, it shows the required width and height instead of crashing.
- The top row shows the GitHub link on the left and "by fsrvr" on the right.

(made for fun)

Made by fsrvr.
