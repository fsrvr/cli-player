# cli-player
A lightweight terminal music player built with Python, curses, and VLC. Folders become playlists, with shuffle, loop, seek, volume, search, color themes, and saved state.

(made for fun)

## Features
- Folders as playlists, scrollable song list with cursor
- Live search/filter within a playlist
- Shuffle, loop (off / song / playlist), seek, volume
- Drag & drop audio files into the terminal to copy or move them into the current playlist
- 7 color themes (default is mono), visualizer follows the theme
- Remembers volume, loop, shuffle, theme, and last song between runs
- Playback speed, synced `.lrc` lyrics, mouse support, play-next queue
- Optional [cava](https://github.com/karlstav/cava) visualizer (Linux)

## Quick install

    git clone https://github.com/fsrvr/cli-player && cd cli-player && ./install.sh

It asks for your OS/distro (arch, debian, ubuntu, mint, fedora, opensuse, void, alpine, macos, freebsd, windows), installs everything, and adds a cli-player command. Windows users: the script prints the PowerShell steps.

## Installation
Works on Arch, Debian/Ubuntu, Fedora, macOS, and Windows. VLC is required. cava is optional.

### Arch
```
sudo pacman -S vlc python-pip cava
pip install -r requirements.txt --break-system-packages
```

### Debian / Ubuntu
```
sudo apt install vlc python3-pip cava
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
| `j` / `k` | Move cursor down / up in song list |
| `Enter` | Play selected song |
| `/` | Search (type to filter, `↑`/`↓` select, `Enter` play, `Esc` cancel) |
| `t` | Cycle color theme |
| `h` | Show help menu |
| `l` | Cycle loop mode (off, song, playlist) |
| `r` | Toggle shuffle |
| `a` | Add selected song to queue |
| `x` / `X` | Remove selected song from queue / clear queue |
| `,` / `.` | Playback speed -0.1x / +0.1x |
| `q` | Quit |

## Lyrics
Put a `.lrc` file next to a song with the same name (`song.mp3` + `song.lrc`). The current line shows above the progress bar.

## Mouse
Click the progress bar to seek, click a song to play it, scroll for volume.

## Drag & drop
Drag an audio file from your file manager onto the terminal window. A popup asks copy or move: pick with `↑`/`↓` and `Enter` (`Esc` cancels). Switch playlists with `[` / `]` first to choose the destination. Needs a terminal that pastes the file path on drop (kitty, foot, alacritty, wezterm, etc.).

## Saved state
Settings are stored in `~/.config/cli-player/state.json` on quit. Delete it to reset.

## License
MIT
