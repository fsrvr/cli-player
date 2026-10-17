# cli-player
A lightweight terminal music player built with Python, curses, and VLC. Folders become playlists, with shuffle, loop, seek, and volume controls.

(made for fun)

## Installation
Works on Arch, Debian/Ubuntu, Fedora, macOS, and Windows. VLC is required.

### Arch
```
sudo pacman -S vlc python-pip
pip install -r requirements.txt --break-system-packages
```

### Debian / Ubuntu
```
sudo apt install vlc python3-pip
pip install -r requirements.txt --break-system-packages
```

### Fedora
VLC needs [RPM Fusion](https://rpmfusion.org/Configuration) enabled first.
```
sudo dnf install vlc python3-pip
pip install -r requirements.txt
```

### macOS
```
brew install --cask vlc
pip install -r requirements.txt
```

### Windows
```
winget install VideoLAN.VLC
pip install -r requirements.txt
```
Use 64-bit Python to match 64-bit VLC.

## Usage
```
python3 cli-player.py [MUSIC_DIR]
```
On Windows use `python cli-player.py [MUSIC_DIR]`.

`MUSIC_DIR` defaults to `~/Documents/music`. Each subfolder is a playlist; loose files in the root go into "All (root)".

```
music/
├── Chill/
│   ├── song1.mp3
│   └── song2.mp3
└── Workout/
    └── song3.mp3
```

Supported formats: mp3, flac, wav, ogg, m4a, opus, wma.

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

## License
MIT
