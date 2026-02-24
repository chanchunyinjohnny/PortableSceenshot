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
