#!/usr/bin/env python3
"""PortableScreenshot - Lightweight screenshot capture tool.

Usage:
    python3 screenshot_tool.py              # Run as tray app
    python3 screenshot_tool.py --once       # Capture once and exit
    python3 screenshot_tool.py --format jpg # Override default format
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# ── Configuration ───────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULTS = {
    "save_directory": str(Path.home() / "Desktop"),
    "format": "png",
    "jpg_quality": 95,
}


def load_config():
    """Load config from file, merging with defaults for missing keys."""
    try:
        with open(CONFIG_PATH) as f:
            return {**DEFAULTS, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save_config(cfg):
    """Persist config to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Post-Capture ────────────────────────────────────────────────────────

def generate_filename(cfg):
    """Generate a timestamped filename like Screenshot_20260224_143052.png"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:22]
    return f"Screenshot_{ts}.{cfg['format']}"


def save_screenshot(pixmap, cfg):
    """Save QPixmap to file, copy to clipboard, and show notification.

    Returns the saved file path, or None on failure.
    """
    from PyQt5.QtWidgets import QApplication

    filename = generate_filename(cfg)
    save_dir = cfg["save_directory"]
    os.makedirs(save_dir, exist_ok=True)
    out_path = os.path.join(save_dir, filename)

    fmt = cfg["format"]
    if fmt == "png":
        if not pixmap.save(out_path, "PNG"):
            return None
    else:
        from PyQt5.QtGui import QImage
        from PIL import Image
        qimage = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        buffer = qimage.bits().asstring(qimage.sizeInBytes())
        img = Image.frombuffer(
            "RGBA",
            (qimage.width(), qimage.height()),
            buffer, "raw", "BGRA", 0, 1,
        )
        img.convert("RGB").save(
            out_path, "JPEG", quality=cfg.get("jpg_quality", 95)
        )

    # Copy to clipboard
    clipboard = QApplication.clipboard()
    clipboard.setPixmap(pixmap)

    return out_path


# ── Screen Capture ──────────────────────────────────────────────────────

def grab_virtual_desktop():
    """Capture the entire virtual desktop (all monitors) as a QPixmap."""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QPixmap, QPainter
    from PyQt5.QtCore import QRect

    screens = QApplication.screens()
    if not screens:
        return None

    combined = QRect()
    for screen in screens:
        combined = combined.united(screen.geometry())

    result = QPixmap(combined.size())
    result.fill()
    painter = QPainter(result)

    for screen in screens:
        geo = screen.geometry()
        screenshot = screen.grabWindow(0)
        painter.drawPixmap(
            geo.x() - combined.x(),
            geo.y() - combined.y(),
            screenshot,
        )

    painter.end()
    return result


def capture_fullscreen(cfg):
    """Capture full virtual desktop and save."""
    pixmap = grab_virtual_desktop()
    if pixmap and not pixmap.isNull():
        return save_screenshot(pixmap, cfg)
    return None


# ── Region Selector Overlay ─────────────────────────────────────────────

from PyQt5.QtWidgets import QWidget, QLabel
from PyQt5.QtGui import QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QRect, QPoint, QThread, pyqtSignal


class RegionSelector(QWidget):
    """Fullscreen transparent overlay for rubber-band region selection."""

    region_selected = pyqtSignal(QRect)
    selection_cancelled = pyqtSignal()

    def __init__(self, background_pixmap, virtual_geometry):
        super().__init__()
        self.background = background_pixmap
        self.virtual_geo = virtual_geometry
        self.origin = QPoint()
        self.current = QPoint()
        self.selecting = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setGeometry(virtual_geometry)
        self.setCursor(Qt.CrossCursor)

        self.size_label = QLabel(self)
        self.size_label.setStyleSheet(
            "background-color: rgba(0,0,0,180); color: white; "
            "padding: 2px 6px; border-radius: 3px; font-size: 12px;"
        )
        self.size_label.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.background)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        if self.selecting:
            rect = QRect(self.origin, self.current).normalized()
            if not rect.isEmpty():
                painter.setCompositionMode(QPainter.CompositionMode_Source)
                painter.drawPixmap(rect, self.background, rect)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

                pen = QPen(QColor(0, 174, 255), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            self.current = event.pos()
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.selecting:
            self.current = event.pos()
            self.update()

            rect = QRect(self.origin, self.current).normalized()
            self.size_label.setText(f" {rect.width()} x {rect.height()} ")
            self.size_label.adjustSize()
            label_pos = event.pos() + QPoint(15, 15)
            self.size_label.move(label_pos)
            self.size_label.show()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.selecting:
            self.selecting = False
            rect = QRect(self.origin, self.current).normalized()
            self.close()
            if rect.width() > 5 and rect.height() > 5:
                self.region_selected.emit(rect)
            else:
                self.selection_cancelled.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.selecting = False
            self.close()
            self.selection_cancelled.emit()


def capture_region(cfg, app_ref=None):
    """Show overlay for region selection, then save the cropped region."""
    from PyQt5.QtWidgets import QApplication

    desktop_pixmap = grab_virtual_desktop()
    if desktop_pixmap is None or desktop_pixmap.isNull():
        return None

    screens = QApplication.screens()
    combined = QRect()
    for screen in screens:
        combined = combined.united(screen.geometry())

    selector = RegionSelector(desktop_pixmap, combined)

    def on_region_selected(rect):
        cropped = desktop_pixmap.copy(rect)
        path = save_screenshot(cropped, cfg)
        if path and app_ref and hasattr(app_ref, 'notify'):
            app_ref.notify(path)

    selector.region_selected.connect(on_region_selected)
    selector.showFullScreen()
    return selector


# ── Active Window Capture ───────────────────────────────────────────────

def get_foreground_window_rect():
    """Get the foreground window's rectangle using Windows API.
    Returns QRect or None.
    """
    if sys.platform != "win32":
        return None

    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    return QRect(rect.left, rect.top,
                 rect.right - rect.left, rect.bottom - rect.top)


def capture_window(cfg):
    """Capture the currently active window and save."""
    from PyQt5.QtWidgets import QApplication

    win_rect = get_foreground_window_rect()

    if win_rect is None:
        return capture_fullscreen(cfg)

    desktop_pixmap = grab_virtual_desktop()
    if desktop_pixmap is None or desktop_pixmap.isNull():
        return None

    screens = QApplication.screens()
    combined = QRect()
    for screen in screens:
        combined = combined.united(screen.geometry())

    crop_rect = QRect(
        win_rect.x() - combined.x(),
        win_rect.y() - combined.y(),
        win_rect.width(),
        win_rect.height(),
    )
    cropped = desktop_pixmap.copy(crop_rect)
    return save_screenshot(cropped, cfg)


# ── Global Hotkey Listener (Windows) ────────────────────────────────────

class HotkeyListener(QThread):
    """Background thread that registers and listens for global hotkeys on Windows."""

    region_hotkey = pyqtSignal()
    fullscreen_hotkey = pyqtSignal()
    window_hotkey = pyqtSignal()

    ID_REGION = 1
    ID_FULLSCREEN = 2
    ID_WINDOW = 3

    MOD_CTRL = 0x0002
    MOD_ALT = 0x0001

    def __init__(self):
        super().__init__()
        self._running = True

    def run(self):
        if sys.platform != "win32":
            return

        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32

        mods = self.MOD_CTRL | self.MOD_ALT
        hotkeys = [
            (self.ID_REGION, ord('P'), "Ctrl+Alt+P"),
            (self.ID_FULLSCREEN, ord('F'), "Ctrl+Alt+F"),
            (self.ID_WINDOW, ord('W'), "Ctrl+Alt+W"),
        ]
        for hk_id, vk, label in hotkeys:
            if not user32.RegisterHotKey(None, hk_id, mods, vk):
                print(f"[Warning] Could not register {label} (already in use)")

        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == 0x0312:  # WM_HOTKEY
                hotkey_id = msg.wParam
                if hotkey_id == self.ID_REGION:
                    self.region_hotkey.emit()
                elif hotkey_id == self.ID_FULLSCREEN:
                    self.fullscreen_hotkey.emit()
                elif hotkey_id == self.ID_WINDOW:
                    self.window_hotkey.emit()

        user32.UnregisterHotKey(None, self.ID_REGION)
        user32.UnregisterHotKey(None, self.ID_FULLSCREEN)
        user32.UnregisterHotKey(None, self.ID_WINDOW)

    def stop(self):
        self._running = False
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(
                int(self.currentThreadId()), 0x0012, 0, 0  # WM_QUIT
            )


# ── Tray Icon ───────────────────────────────────────────────────────────

def make_tray_icon():
    """Generate a simple crosshair-in-frame icon programmatically."""
    from PyQt5.QtGui import QIcon, QPixmap

    px = QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    dark = QColor(50, 50, 50)
    p.setPen(QPen(dark, 2.5, Qt.DashLine))
    p.drawRect(8, 8, 48, 48)
    p.setPen(QPen(dark, 2))
    p.drawLine(32, 14, 32, 50)
    p.drawLine(14, 32, 50, 32)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(200, 50, 50))
    p.drawEllipse(27, 27, 10, 10)
    p.end()
    return QIcon(px)


# ── Main Application ────────────────────────────────────────────────────

from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QAction,
    QFileDialog, QActionGroup,
)


class ScreenshotApp:
    """System tray screenshot application."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("PortableScreenshot")

        self._selector_ref = None  # prevent GC of overlay widget

        # Tray icon
        self.tray = QSystemTrayIcon(make_tray_icon())
        self.tray.setToolTip("PortableScreenshot")
        self.tray.activated.connect(self._on_tray_activated)

        # Context menu
        self._build_menu()

        # Hotkey listener
        self.hotkey_listener = HotkeyListener()
        self.hotkey_listener.region_hotkey.connect(self.do_region_capture)
        self.hotkey_listener.fullscreen_hotkey.connect(self.do_fullscreen_capture)
        self.hotkey_listener.window_hotkey.connect(self.do_window_capture)
        self.hotkey_listener.start()

        self.tray.show()
        self._show_startup_message()

    def _build_menu(self):
        menu = QMenu()

        menu.addAction("Capture Region\tCtrl+Alt+P", self.do_region_capture)
        menu.addAction("Capture Full Screen\tCtrl+Alt+F", self.do_fullscreen_capture)
        menu.addAction("Capture Window\tCtrl+Alt+W", self.do_window_capture)
        menu.addSeparator()

        # Format submenu
        fmt_menu = menu.addMenu("Format")
        grp = QActionGroup(menu)
        grp.setExclusive(True)
        self._format_actions = {}
        for f in ("png", "jpg"):
            a = QAction(f.upper(), grp)
            a.setCheckable(True)
            a.setChecked(self.cfg["format"] == f)
            a.triggered.connect(lambda _, fmt=f: self._set_format(fmt))
            fmt_menu.addAction(a)
            self._format_actions[f] = a

        # Save location
        menu.addAction("Save Location...", self._choose_save_dir)
        self._loc_action = menu.addAction(f"  {self.cfg['save_directory']}")
        self._loc_action.setEnabled(False)

        menu.addSeparator()
        menu.addAction("Quit", self._quit)

        self.tray.setContextMenu(menu)

    def _show_startup_message(self):
        hotkey_str = "Ctrl+Alt+P" if sys.platform == "win32" else "click icon"
        self.tray.showMessage(
            "PortableScreenshot",
            f"{hotkey_str} to capture region\n"
            f"Format: {self.cfg['format'].upper()} | "
            f"Save: {self.cfg['save_directory']}",
            QSystemTrayIcon.Information, 3000,
        )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.do_region_capture()

    def do_region_capture(self):
        self._selector_ref = capture_region(self.cfg, app_ref=self)

    def do_fullscreen_capture(self):
        path = capture_fullscreen(self.cfg)
        if path:
            self.notify(path)

    def do_window_capture(self):
        path = capture_window(self.cfg)
        if path:
            self.notify(path)

    def notify(self, path):
        self.tray.showMessage(
            "Screenshot Saved",
            os.path.basename(path),
            QSystemTrayIcon.Information, 2000,
        )

    def _set_format(self, fmt):
        self.cfg["format"] = fmt
        save_config(self.cfg)
        for f, action in self._format_actions.items():
            action.setChecked(f == fmt)

    def _choose_save_dir(self):
        d = QFileDialog.getExistingDirectory(
            None, "Choose Save Location", self.cfg["save_directory"]
        )
        if d:
            self.cfg["save_directory"] = d
            save_config(self.cfg)
            self._loc_action.setText(f"  {d}")

    def _quit(self):
        save_config(self.cfg)
        self.hotkey_listener.stop()
        self.hotkey_listener.wait(2000)
        self.tray.hide()
        self.app.quit()

    def run(self):
        return self.app.exec_()


# ── CLI Entry Point ─────────────────────────────────────────────────────

import argparse


def _enable_dpi_awareness():
    """Enable DPI awareness on Windows for correct coordinate handling."""
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def main():
    _enable_dpi_awareness()

    parser = argparse.ArgumentParser(
        description="PortableScreenshot - lightweight screenshot tool"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Capture once and exit (no tray app)",
    )
    parser.add_argument(
        "--format", choices=["png", "jpg"], dest="fmt",
        help="Image format override",
    )
    parser.add_argument(
        "--save-dir",
        help="Save directory override",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.fmt:
        cfg["format"] = args.fmt
    if args.save_dir:
        cfg["save_directory"] = args.save_dir

    if args.once:
        app = QApplication(sys.argv)
        path = capture_fullscreen(cfg)
        if path:
            print(f"Saved: {path}")
        return 0 if path else 1

    return ScreenshotApp(cfg).run()


if __name__ == "__main__":
    sys.exit(main())
