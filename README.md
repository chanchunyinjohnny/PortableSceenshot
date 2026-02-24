# PortableScreenshot

A lightweight, portable screenshot capture tool for Windows inspired by [Greenshot](https://getgreenshot.org/). Runs as a system tray application with global hotkeys for quick region, fullscreen, and active window captures.

## Features

- **Region capture** — select any area of the screen with a drag-to-select overlay
- **Fullscreen capture** — capture all monitors at once
- **Active window capture** — capture just the currently focused window
- **Global hotkeys** — trigger captures from any application without clicking
- **System tray** — lives in the taskbar, always ready
- **Clipboard copy** — every screenshot is automatically copied to clipboard for pasting
- **PNG / JPG** — switch formats on the fly from the tray menu
- **Multi-monitor** — works across multiple displays
- **No admin required** — runs entirely in user space

## Requirements

- Python 3.9+
- PyQt5 >= 5.15
- Pillow >= 10.0

## Installation

### Option A: pip

```bash
pip install -r requirements.txt
```

### Option B: conda

```bash
conda env create -f environment.yml
conda activate portable-screenshot
```

### Option C: editable install (for development)

```bash
pip install -e .
```

## Usage

### Start the tray app

```bash
python screenshot_tool.py
```

A crosshair icon appears in the system tray (bottom-right of the taskbar). A notification confirms the app is ready.

### Hotkeys

| Shortcut | Action |
|---|---|
| **Ctrl+Alt+P** | Capture a region (drag to select) |
| **Ctrl+Alt+F** | Capture the full screen |
| **Ctrl+Alt+W** | Capture the active window |

### Region capture

1. Press **Ctrl+Alt+P** (or left-click the tray icon)
2. The screen dims with a crosshair cursor
3. Click and drag to select the area you want
4. A live **W x H** label shows the selection size
5. Release the mouse — the screenshot is saved and copied to clipboard
6. Press **Escape** at any time to cancel

### Tray menu (right-click the icon)

```
Capture Region          Ctrl+Alt+P
Capture Full Screen     Ctrl+Alt+F
Capture Window          Ctrl+Alt+W
────────────────────────
Format  ►  ○ PNG
            ● JPG
────────────────────────
Save Location...
  C:\Users\You\Desktop
────────────────────────
Quit
```

- **Format** — toggle between PNG (lossless) and JPG (smaller file size, quality 95)
- **Save Location** — opens a folder picker to change where screenshots are saved
- **Quit** — exit the application

### Where are screenshots saved?

By default: your **Desktop** folder.

Files are named with a timestamp: `Screenshot_20260224_143052_123456.png`

You can change the save location anytime via the tray menu.

### One-shot mode (no tray)

For scripting or quick use without the tray app:

```bash
# Capture fullscreen and exit
python screenshot_tool.py --once

# Capture as JPG
python screenshot_tool.py --once --format jpg

# Save to a specific folder
python screenshot_tool.py --once --save-dir "C:\Users\You\Pictures"
```

## Configuration

Settings are stored in `config.json` next to the script and persist between sessions. You can edit this file directly or use the tray menu.

```json
{
  "save_directory": "C:\\Users\\You\\Desktop",
  "format": "png",
  "jpg_quality": 95
}
```

| Key | Values | Description |
|---|---|---|
| `save_directory` | Any folder path | Where screenshots are saved |
| `format` | `"png"` or `"jpg"` | Image format |
| `jpg_quality` | 1–100 | JPEG compression quality (higher = better quality, larger file) |

## Running Tests

```bash
pytest test_screenshot_tool.py -v
```

## Troubleshooting

**Hotkeys not working?**
Another application may have already registered the same key combination. The console will print a warning like `[Warning] Could not register Ctrl+Alt+P (already in use)`. Close the conflicting app or use the tray menu to capture instead.

**Screenshots look wrong on high-DPI displays?**
The app enables DPI awareness automatically. If you still see scaling issues, check your Windows display scaling settings (Settings > Display > Scale).

**Tray icon not visible?**
On Windows 10/11, new tray icons may be hidden. Click the **^** arrow in the taskbar to find it, then drag it to the visible area.

## Support

If you find this tool useful, consider supporting the project:

- [GitHub Sponsors](https://github.com/sponsors/chanchunyinjohnny)
- [Buy Me a Coffee](https://buymeacoffee.com/chanchunyinjohnny)
- [Ko-fi](https://ko-fi.com/chanchunyinjohnny)

## License

MIT
