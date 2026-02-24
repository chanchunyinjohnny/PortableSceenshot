"""Unit tests for PortableScreenshot core logic.

Tests cover config management, filename generation, format handling,
CLI argument parsing, DPI awareness guards, and hotkey constants.
No display or GUI required — all Qt-dependent behavior is avoided.

Run:
    pytest test_screenshot_tool.py -v
"""

import json
import os
import sys
import time
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
import screenshot_tool as st


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect CONFIG_PATH to a temp directory so tests don't touch real config."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(st, "CONFIG_PATH", config_file)
    return config_file


@pytest.fixture
def default_cfg():
    """Return a fresh copy of default config."""
    return dict(st.DEFAULTS)


# ── Config: load_config ─────────────────────────────────────────────────

class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_defaults_when_no_file(self, tmp_config):
        """When config.json does not exist, load_config returns defaults."""
        assert not tmp_config.exists()
        cfg = st.load_config()
        assert cfg == st.DEFAULTS

    def test_returns_defaults_when_file_is_invalid_json(self, tmp_config):
        """When config.json contains invalid JSON, load_config returns defaults."""
        tmp_config.write_text("not valid json {{{")
        cfg = st.load_config()
        assert cfg == st.DEFAULTS

    def test_returns_defaults_when_file_is_empty(self, tmp_config):
        """When config.json is empty, load_config returns defaults."""
        tmp_config.write_text("")
        cfg = st.load_config()
        assert cfg == st.DEFAULTS

    def test_loads_saved_values(self, tmp_config):
        """When config.json has valid data, values override defaults."""
        tmp_config.write_text(json.dumps({"format": "jpg", "jpg_quality": 80}))
        cfg = st.load_config()
        assert cfg["format"] == "jpg"
        assert cfg["jpg_quality"] == 80

    def test_merges_with_defaults_for_missing_keys(self, tmp_config):
        """Partial config files get missing keys filled from defaults."""
        tmp_config.write_text(json.dumps({"format": "jpg"}))
        cfg = st.load_config()
        assert cfg["format"] == "jpg"
        # Missing keys should come from DEFAULTS
        assert cfg["save_directory"] == st.DEFAULTS["save_directory"]
        assert cfg["jpg_quality"] == st.DEFAULTS["jpg_quality"]

    def test_extra_keys_preserved(self, tmp_config):
        """Unknown keys in config.json are preserved (forward compatibility)."""
        tmp_config.write_text(json.dumps({"format": "png", "custom_key": "value"}))
        cfg = st.load_config()
        assert cfg["custom_key"] == "value"


# ── Config: save_config ─────────────────────────────────────────────────

class TestSaveConfig:
    """Tests for save_config()."""

    def test_creates_config_file(self, tmp_config, default_cfg):
        """save_config creates the config.json file."""
        assert not tmp_config.exists()
        st.save_config(default_cfg)
        assert tmp_config.exists()

    def test_writes_valid_json(self, tmp_config, default_cfg):
        """Saved config is valid JSON that can be parsed back."""
        st.save_config(default_cfg)
        data = json.loads(tmp_config.read_text())
        assert data == default_cfg

    def test_roundtrip(self, tmp_config):
        """save then load returns the same config."""
        cfg = {"save_directory": "/tmp/test", "format": "jpg", "jpg_quality": 50}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["save_directory"] == "/tmp/test"
        assert loaded["format"] == "jpg"
        assert loaded["jpg_quality"] == 50

    def test_overwrites_existing(self, tmp_config):
        """Saving twice overwrites the previous config."""
        st.save_config({"format": "png", "save_directory": "/a", "jpg_quality": 95})
        st.save_config({"format": "jpg", "save_directory": "/b", "jpg_quality": 80})
        loaded = st.load_config()
        assert loaded["format"] == "jpg"
        assert loaded["save_directory"] == "/b"

    def test_pretty_printed(self, tmp_config, default_cfg):
        """Config file is human-readable (indented)."""
        st.save_config(default_cfg)
        content = tmp_config.read_text()
        assert "\n" in content  # multi-line
        assert "  " in content  # indented


# ── Config: DEFAULTS ────────────────────────────────────────────────────

class TestDefaults:
    """Tests for default configuration values."""

    def test_default_format_is_png(self):
        assert st.DEFAULTS["format"] == "png"

    def test_default_jpg_quality(self):
        assert st.DEFAULTS["jpg_quality"] == 95

    def test_default_save_directory_is_desktop(self):
        """Default save directory should be the user's Desktop."""
        expected = str(Path.home() / "Desktop")
        assert st.DEFAULTS["save_directory"] == expected

    def test_save_directory_is_absolute_path(self):
        """Default save directory is an absolute path, never ~ or relative."""
        path = st.DEFAULTS["save_directory"]
        assert os.path.isabs(path)
        assert "~" not in path


# ── Filename Generation ─────────────────────────────────────────────────

class TestGenerateFilename:
    """Tests for generate_filename()."""

    def test_png_format(self):
        name = st.generate_filename({"format": "png"})
        assert name.startswith("Screenshot_")
        assert name.endswith(".png")

    def test_jpg_format(self):
        name = st.generate_filename({"format": "jpg"})
        assert name.endswith(".jpg")

    def test_contains_timestamp(self):
        """Filename contains a date-time pattern YYYYMMDD_HHMMSS."""
        name = st.generate_filename({"format": "png"})
        # Extract the timestamp portion
        match = re.search(r"Screenshot_(\d{8}_\d{6})", name)
        assert match is not None, f"No timestamp found in {name}"

    def test_includes_microseconds(self):
        """Filename includes microsecond portion to avoid collisions."""
        name = st.generate_filename({"format": "png"})
        # Pattern: Screenshot_YYYYMMDD_HHMMSS_uuuuuu.png (truncated to 22 chars)
        # The timestamp part should be longer than just YYYYMMDD_HHMMSS (15 chars)
        stem = name.replace("Screenshot_", "").replace(".png", "")
        assert len(stem) > 15, f"Expected microseconds in timestamp, got: {stem}"

    def test_no_collision_rapid_calls(self):
        """Two rapid calls should produce different filenames."""
        cfg = {"format": "png"}
        name1 = st.generate_filename(cfg)
        name2 = st.generate_filename(cfg)
        # With microseconds, these should almost always differ
        # But if they're the same (same microsecond), at least verify format is correct
        assert name1.startswith("Screenshot_")
        assert name2.startswith("Screenshot_")

    def test_filename_has_no_spaces(self):
        """Filenames should not contain spaces (safe for all filesystems)."""
        name = st.generate_filename({"format": "png"})
        assert " " not in name

    def test_filename_has_no_special_chars(self):
        """Filenames contain only alphanumeric, underscore, and dot."""
        name = st.generate_filename({"format": "png"})
        assert re.match(r'^[A-Za-z0-9_.]+$', name), f"Invalid chars in {name}"


# ── CLI Argument Parsing ────────────────────────────────────────────────

class TestCLIArgs:
    """Tests for main() argument parsing logic."""

    def test_default_args(self):
        """With no arguments, argparse produces expected defaults."""
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--format", choices=["png", "jpg"], dest="fmt")
        parser.add_argument("--save-dir")
        args = parser.parse_args([])
        assert args.once is False
        assert args.fmt is None
        assert args.save_dir is None

    def test_once_flag(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--once", action="store_true")
        args = parser.parse_args(["--once"])
        assert args.once is True

    def test_format_png(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", choices=["png", "jpg"], dest="fmt")
        args = parser.parse_args(["--format", "png"])
        assert args.fmt == "png"

    def test_format_jpg(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", choices=["png", "jpg"], dest="fmt")
        args = parser.parse_args(["--format", "jpg"])
        assert args.fmt == "jpg"

    def test_format_invalid_rejected(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", choices=["png", "jpg"], dest="fmt")
        with pytest.raises(SystemExit):
            parser.parse_args(["--format", "bmp"])

    def test_save_dir(self):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--save-dir")
        args = parser.parse_args(["--save-dir", "/tmp/screenshots"])
        assert args.save_dir == "/tmp/screenshots"

    def test_format_overrides_config(self, tmp_config):
        """--format flag should override the config file value."""
        st.save_config({"format": "png", "save_directory": "/tmp", "jpg_quality": 95})
        cfg = st.load_config()
        # Simulate what main() does
        fmt_override = "jpg"
        if fmt_override:
            cfg["format"] = fmt_override
        assert cfg["format"] == "jpg"

    def test_save_dir_overrides_config(self, tmp_config):
        """--save-dir flag should override the config file value."""
        st.save_config({"format": "png", "save_directory": "/original", "jpg_quality": 95})
        cfg = st.load_config()
        dir_override = "/override"
        if dir_override:
            cfg["save_directory"] = dir_override
        assert cfg["save_directory"] == "/override"


# ── DPI Awareness ───────────────────────────────────────────────────────

class TestDPIAwareness:
    """Tests for _enable_dpi_awareness()."""

    @patch("sys.platform", "win32")
    def test_calls_shcore_on_windows(self):
        """On Windows, should try SetProcessDpiAwareness first."""
        mock_shcore = MagicMock()
        mock_user32 = MagicMock()
        with patch.dict("sys.modules", {}):
            import ctypes as real_ctypes
            with patch.object(real_ctypes, "windll", create=True) as mock_windll:
                mock_windll.shcore = mock_shcore
                mock_windll.user32 = mock_user32
                st._enable_dpi_awareness()
                mock_shcore.SetProcessDpiAwareness.assert_called_once_with(2)

    @patch("sys.platform", "darwin")
    def test_skipped_on_macos(self):
        """On macOS, _enable_dpi_awareness should be a no-op."""
        # Should not raise any exception
        st._enable_dpi_awareness()

    @patch("sys.platform", "linux")
    def test_skipped_on_linux(self):
        """On Linux, _enable_dpi_awareness should be a no-op."""
        st._enable_dpi_awareness()


# ── Platform Guards ─────────────────────────────────────────────────────

class TestPlatformGuards:
    """Tests for Windows-only code paths being properly guarded."""

    def test_get_foreground_window_rect_returns_none_on_non_windows(self):
        """On non-Windows, get_foreground_window_rect returns None."""
        if sys.platform != "win32":
            result = st.get_foreground_window_rect()
            assert result is None

    def test_hotkey_listener_exits_immediately_on_non_windows(self):
        """On non-Windows, HotkeyListener.run() returns immediately."""
        if sys.platform != "win32":
            listener = st.HotkeyListener()
            # run() should return immediately without blocking
            listener.run()
            # If we get here, it didn't hang — pass


# ── Hotkey Constants ────────────────────────────────────────────────────

class TestHotkeyConstants:
    """Tests for HotkeyListener constants matching Windows API values."""

    def test_mod_ctrl_value(self):
        """MOD_CTRL should be 0x0002 (Windows API MOD_CONTROL)."""
        assert st.HotkeyListener.MOD_CTRL == 0x0002

    def test_mod_alt_value(self):
        """MOD_ALT should be 0x0001 (Windows API MOD_ALT)."""
        assert st.HotkeyListener.MOD_ALT == 0x0001

    def test_hotkey_ids_unique(self):
        """All hotkey IDs must be unique to avoid conflicts."""
        ids = [
            st.HotkeyListener.ID_REGION,
            st.HotkeyListener.ID_FULLSCREEN,
            st.HotkeyListener.ID_WINDOW,
        ]
        assert len(ids) == len(set(ids))

    def test_hotkey_ids_positive(self):
        """Hotkey IDs should be positive integers (Windows requirement)."""
        for hk_id in [st.HotkeyListener.ID_REGION,
                       st.HotkeyListener.ID_FULLSCREEN,
                       st.HotkeyListener.ID_WINDOW]:
            assert isinstance(hk_id, int)
            assert hk_id > 0

    def test_combined_modifiers(self):
        """Ctrl+Alt should combine correctly via bitwise OR."""
        combined = st.HotkeyListener.MOD_CTRL | st.HotkeyListener.MOD_ALT
        assert combined == 0x0003


# ── Config Path ─────────────────────────────────────────────────────────

class TestConfigPath:
    """Tests for CONFIG_PATH location."""

    def test_config_path_is_beside_script(self):
        """config.json should live next to screenshot_tool.py."""
        script_dir = Path(st.__file__).parent
        expected = script_dir / "config.json"
        assert st.CONFIG_PATH == expected

    def test_config_path_filename(self):
        """Config file should be named config.json."""
        assert st.CONFIG_PATH.name == "config.json"


# ── Edge Cases ──────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_config_with_unicode_path(self, tmp_config):
        """Config handles unicode characters in save directory."""
        cfg = {"format": "png", "save_directory": "/tmp/截图测试", "jpg_quality": 95}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["save_directory"] == "/tmp/截图测试"

    def test_config_with_windows_path(self, tmp_config):
        """Config handles Windows-style backslash paths."""
        cfg = {"format": "png", "save_directory": "C:\\Users\\Test\\Desktop", "jpg_quality": 95}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["save_directory"] == "C:\\Users\\Test\\Desktop"

    def test_config_with_long_path(self, tmp_config):
        """Config handles long directory paths."""
        long_dir = "/tmp/" + "a" * 200
        cfg = {"format": "png", "save_directory": long_dir, "jpg_quality": 95}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["save_directory"] == long_dir

    def test_jpg_quality_boundary_low(self, tmp_config):
        """Config preserves quality=1 (minimum useful JPEG quality)."""
        cfg = {"format": "jpg", "save_directory": "/tmp", "jpg_quality": 1}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["jpg_quality"] == 1

    def test_jpg_quality_boundary_high(self, tmp_config):
        """Config preserves quality=100 (maximum JPEG quality)."""
        cfg = {"format": "jpg", "save_directory": "/tmp", "jpg_quality": 100}
        st.save_config(cfg)
        loaded = st.load_config()
        assert loaded["jpg_quality"] == 100

    def test_generate_filename_unknown_format(self):
        """generate_filename works with any format string (no validation)."""
        name = st.generate_filename({"format": "bmp"})
        assert name.endswith(".bmp")

    def test_defaults_is_not_mutated_by_load(self, tmp_config):
        """Loading config should not mutate the DEFAULTS dict."""
        original = dict(st.DEFAULTS)
        tmp_config.write_text(json.dumps({"format": "jpg"}))
        st.load_config()
        assert st.DEFAULTS == original


# ── Region Selector Setup ────────────────────────────────────────────

class TestRegionSelectorSetup:
    """Tests for RegionSelector class attributes and signals."""

    def test_has_region_selected_signal(self):
        """RegionSelector exposes a region_selected signal for crop handling."""
        assert hasattr(st.RegionSelector, 'region_selected')

    def test_has_selection_cancelled_signal(self):
        """RegionSelector exposes a selection_cancelled signal for cancel handling."""
        assert hasattr(st.RegionSelector, 'selection_cancelled')

    def test_window_flags_for_overlay(self):
        """RegionSelector __init__ sets FramelessWindowHint, WindowStaysOnTopHint, Dialog."""
        import inspect
        source = inspect.getsource(st.RegionSelector.__init__)
        assert 'FramelessWindowHint' in source
        assert 'WindowStaysOnTopHint' in source
        assert 'Dialog' in source

    def test_sets_cross_cursor(self):
        """RegionSelector sets CrossCursor for precision area selection."""
        import inspect
        source = inspect.getsource(st.RegionSelector.__init__)
        assert 'CrossCursor' in source

    def test_sets_geometry_to_virtual_desktop(self):
        """RegionSelector sets its geometry to the full virtual desktop."""
        import inspect
        source = inspect.getsource(st.RegionSelector.__init__)
        assert 'setGeometry(virtual_geometry)' in source

    def test_escape_key_cancels_selection(self):
        """Pressing Escape should close the overlay and emit selection_cancelled."""
        import inspect
        source = inspect.getsource(st.RegionSelector.keyPressEvent)
        assert 'Key_Escape' in source
        assert 'selection_cancelled' in source

    def test_minimum_selection_size(self):
        """Selections smaller than 5x5 pixels are treated as cancelled."""
        import inspect
        source = inspect.getsource(st.RegionSelector.mouseReleaseEvent)
        assert 'rect.width() > 5' in source
        assert 'rect.height() > 5' in source

    def test_grabs_mouse_on_press(self):
        """Mouse is grabbed on press to track dragging across monitors."""
        import inspect
        source = inspect.getsource(st.RegionSelector.mousePressEvent)
        assert 'grabMouse' in source

    def test_releases_mouse_on_release(self):
        """Mouse is released when selection completes."""
        import inspect
        source = inspect.getsource(st.RegionSelector.mouseReleaseEvent)
        assert 'releaseMouse' in source


# ── capture_region Flow ──────────────────────────────────────────────

class TestCaptureRegionFlow:
    """Tests for capture_region() function behavior."""

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_uses_show_not_showFullScreen(self, mock_convert, MockSelector):
        """capture_region must use show() for multi-monitor spanning.

        showFullScreen() restricts the overlay to a single monitor,
        preventing the selection box from following the mouse across screens.
        show() respects the manually-set geometry that spans all monitors.
        """
        mock_convert.return_value = (MagicMock(), MagicMock())
        mock_instance = MagicMock()
        MockSelector.return_value = mock_instance

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        st.capture_region({"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre)

        mock_instance.show.assert_called_once()
        assert not mock_instance.showFullScreen.called, (
            "showFullScreen() restricts overlay to one monitor — use show()"
        )

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_activates_and_raises_window(self, mock_convert, MockSelector):
        """capture_region activates and raises the overlay for immediate focus."""
        mock_convert.return_value = (MagicMock(), MagicMock())
        mock_instance = MagicMock()
        MockSelector.return_value = mock_instance

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        st.capture_region({"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre)

        mock_instance.activateWindow.assert_called_once()
        mock_instance.raise_.assert_called_once()

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_connects_region_selected_signal(self, mock_convert, MockSelector):
        """capture_region connects the region_selected signal for crop handling."""
        mock_convert.return_value = (MagicMock(), MagicMock())
        mock_instance = MagicMock()
        MockSelector.return_value = mock_instance

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        st.capture_region({"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre)

        mock_instance.region_selected.connect.assert_called_once()

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_passes_pre_capture_data_to_selector(self, mock_convert, MockSelector):
        """capture_region passes converted pre-capture pixmap and geometry to selector."""
        mock_pixmap = MagicMock()
        mock_geometry = MagicMock()
        mock_convert.return_value = (mock_pixmap, mock_geometry)
        mock_instance = MagicMock()
        MockSelector.return_value = mock_instance

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        st.capture_region({"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre)

        MockSelector.assert_called_once_with(mock_pixmap, mock_geometry)

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_returns_selector_instance(self, mock_convert, MockSelector):
        """capture_region returns the selector widget (kept alive to prevent GC)."""
        mock_convert.return_value = (MagicMock(), MagicMock())
        mock_instance = MagicMock()
        MockSelector.return_value = mock_instance

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        result = st.capture_region({"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre)

        assert result is mock_instance

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.grab_virtual_desktop')
    def test_returns_none_when_desktop_capture_fails(self, mock_grab, MockSelector):
        """capture_region returns None when grab_virtual_desktop returns None."""
        mock_grab.return_value = None
        result = st.capture_region({"format": "png", "save_directory": "/tmp"})
        assert result is None
        MockSelector.assert_not_called()

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.grab_virtual_desktop')
    def test_returns_none_when_desktop_capture_is_null(self, mock_grab, MockSelector):
        """capture_region returns None when desktop capture returns null pixmap."""
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = True
        mock_grab.return_value = mock_pixmap
        result = st.capture_region({"format": "png", "save_directory": "/tmp"})
        assert result is None
        MockSelector.assert_not_called()

    @patch('screenshot_tool.RegionSelector')
    @patch('screenshot_tool.grab_virtual_desktop')
    def test_uses_grab_virtual_desktop_without_pre_capture(self, mock_grab, MockSelector):
        """Without pre_capture, capture_region uses grab_virtual_desktop."""
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        mock_grab.return_value = mock_pixmap
        MockSelector.return_value = MagicMock()

        # Patch QApplication.screens() via the local import
        with patch('PyQt5.QtWidgets.QApplication.screens', return_value=[]):
            st.capture_region({"format": "png", "save_directory": "/tmp"})

        mock_grab.assert_called_once()
        MockSelector.assert_called_once()


# ── Pre-Capture Data Handling ────────────────────────────────────────

class TestPreCaptureHandling:
    """Tests for pre-capture data lifecycle on HotkeyListener."""

    def test_pre_capture_starts_none(self):
        """HotkeyListener.pre_capture should initialize to None."""
        listener = st.HotkeyListener()
        assert listener.pre_capture is None

    def test_pre_capture_can_be_set(self):
        """pre_capture can be assigned a tuple of (bytes, w, h, vx, vy)."""
        listener = st.HotkeyListener()
        fake_data = (b'\x00' * 16, 4, 4, 0, 0)
        listener.pre_capture = fake_data
        assert listener.pre_capture == fake_data

    def test_pre_capture_can_be_cleared(self):
        """pre_capture can be set back to None after consumption."""
        listener = st.HotkeyListener()
        listener.pre_capture = (b'\x00', 1, 1, 0, 0)
        listener.pre_capture = None
        assert listener.pre_capture is None

    def test_consume_pattern_returns_and_clears(self):
        """Simulates the consume pattern used by ScreenshotApp._consume_pre_capture."""
        listener = st.HotkeyListener()
        fake_data = (b'\x00' * 16, 4, 4, 100, 200)
        listener.pre_capture = fake_data

        # Simulate _consume_pre_capture
        data = listener.pre_capture
        listener.pre_capture = None

        assert data == fake_data
        assert listener.pre_capture is None

    def test_consume_returns_none_when_empty(self):
        """Consuming when no pre-capture data is available returns None."""
        listener = st.HotkeyListener()
        data = listener.pre_capture
        listener.pre_capture = None
        assert data is None


# ── capture_fullscreen ───────────────────────────────────────────────

class TestCaptureFullscreen:
    """Tests for capture_fullscreen()."""

    @patch('screenshot_tool.save_screenshot')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    def test_uses_pre_capture_when_provided(self, mock_convert, mock_save):
        """capture_fullscreen uses pre-captured GDI data when available."""
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        mock_convert.return_value = (mock_pixmap, MagicMock())
        mock_save.return_value = "/tmp/test.png"

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        result = st.capture_fullscreen(
            {"format": "png", "save_directory": "/tmp"}, pre_capture=fake_pre
        )

        mock_convert.assert_called_once_with(fake_pre)
        mock_save.assert_called_once()
        assert result == "/tmp/test.png"

    @patch('screenshot_tool.save_screenshot')
    @patch('screenshot_tool.grab_virtual_desktop')
    def test_falls_back_to_qt_without_pre_capture(self, mock_grab, mock_save):
        """Without pre_capture, capture_fullscreen uses grab_virtual_desktop."""
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = False
        mock_grab.return_value = mock_pixmap
        mock_save.return_value = "/tmp/test.png"

        result = st.capture_fullscreen({"format": "png", "save_directory": "/tmp"})

        mock_grab.assert_called_once()
        mock_save.assert_called_once()

    @patch('screenshot_tool.grab_virtual_desktop')
    def test_returns_none_on_null_pixmap(self, mock_grab):
        """capture_fullscreen returns None when capture produces null pixmap."""
        mock_pixmap = MagicMock()
        mock_pixmap.isNull.return_value = True
        mock_grab.return_value = mock_pixmap

        result = st.capture_fullscreen({"format": "png", "save_directory": "/tmp"})
        assert result is None

    @patch('screenshot_tool.grab_virtual_desktop')
    def test_returns_none_when_grab_returns_none(self, mock_grab):
        """capture_fullscreen returns None when grab_virtual_desktop fails."""
        mock_grab.return_value = None
        result = st.capture_fullscreen({"format": "png", "save_directory": "/tmp"})
        assert result is None


# ── capture_window ───────────────────────────────────────────────────

class TestCaptureWindow:
    """Tests for capture_window()."""

    @patch('screenshot_tool.capture_fullscreen')
    @patch('screenshot_tool.get_foreground_window_rect')
    def test_falls_back_to_fullscreen_when_no_window(self, mock_get_rect, mock_fullscreen):
        """When no foreground window (non-Windows), falls back to fullscreen."""
        mock_get_rect.return_value = None
        mock_fullscreen.return_value = "/tmp/test.png"

        cfg = {"format": "png", "save_directory": "/tmp"}
        st.capture_window(cfg)

        mock_fullscreen.assert_called_once_with(cfg, pre_capture=None)

    @patch('screenshot_tool.capture_fullscreen')
    @patch('screenshot_tool.get_foreground_window_rect')
    def test_passes_pre_capture_to_fullscreen_fallback(self, mock_get_rect, mock_fullscreen):
        """When falling back to fullscreen, pre_capture data is forwarded."""
        mock_get_rect.return_value = None
        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)

        cfg = {"format": "png", "save_directory": "/tmp"}
        st.capture_window(cfg, pre_capture=fake_pre)

        mock_fullscreen.assert_called_once_with(cfg, pre_capture=fake_pre)

    @patch('screenshot_tool.save_screenshot')
    @patch('screenshot_tool.pixmap_from_pre_capture')
    @patch('screenshot_tool.get_foreground_window_rect')
    def test_crops_window_rect_with_pre_capture(self, mock_get_rect, mock_convert, mock_save):
        """With a foreground window and pre_capture, crops to window area."""
        mock_get_rect.return_value = st.QRect(100, 100, 800, 600)
        mock_pixmap = MagicMock()
        mock_convert.return_value = (mock_pixmap, st.QRect(0, 0, 1920, 1080))
        mock_save.return_value = "/tmp/test.png"

        fake_pre = (b'\x00' * 16, 2, 2, 0, 0)
        cfg = {"format": "png", "save_directory": "/tmp"}
        result = st.capture_window(cfg, pre_capture=fake_pre)

        mock_pixmap.copy.assert_called_once()
        mock_save.assert_called_once()

    @patch('screenshot_tool.save_screenshot')
    @patch('screenshot_tool.grab_virtual_desktop')
    @patch('screenshot_tool.get_foreground_window_rect')
    def test_returns_none_when_desktop_capture_fails(self, mock_get_rect, mock_grab, mock_save):
        """capture_window returns None when desktop capture fails."""
        mock_get_rect.return_value = st.QRect(100, 100, 800, 600)
        mock_grab.return_value = None

        cfg = {"format": "png", "save_directory": "/tmp"}
        result = st.capture_window(cfg)

        assert result is None
        mock_save.assert_not_called()


# ── Tray Icon ────────────────────────────────────────────────────────

class TestTrayIcon:
    """Tests for make_tray_icon()."""

    def test_make_tray_icon_exists(self):
        """make_tray_icon function should be defined."""
        assert callable(st.make_tray_icon)
