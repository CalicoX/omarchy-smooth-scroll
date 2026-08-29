#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("smooth_scroll_daemon", ROOT / "daemon.py")
daemon = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daemon)


class DeviceScanTests(unittest.TestCase):
    def test_skip_virtual_and_non_mice(self):
        self.assertTrue(daemon.skip_device_name("Omarchy Smooth Scroll"))
        self.assertTrue(daemon.skip_device_name("Y98 BT5.0 Keyboard"))
        self.assertTrue(daemon.skip_device_name("Wireless Link-KM"))
        self.assertTrue(daemon.skip_device_name("2.4G Wireless Device Consumer Control"))
        self.assertFalse(daemon.skip_device_name("Logitech M720 Triathlon Multi-Device Mouse"))
        self.assertFalse(daemon.skip_device_name("Y98 BT5.0 Mouse"))

    def test_wheel_mouse_needs_move_and_wheel(self):
        rel_m720 = 0x1943
        rel_keyboard_mouse = 0x903
        rel_hwheel_only = 0x1040
        self.assertTrue(daemon.looks_like_wheel_mouse("Logitech M720", rel_m720))
        self.assertTrue(daemon.looks_like_wheel_mouse("2.4G Wireless Device Mouse", rel_keyboard_mouse))
        self.assertFalse(daemon.looks_like_wheel_mouse("Consumer Control", rel_hwheel_only))
        self.assertFalse(daemon.looks_like_wheel_mouse("Omarchy Smooth Scroll", rel_m720))

    def test_sysfs_bitmap_btn_bits(self):
        m720 = daemon.parse_sysfs_bitmap("ffff0000 1000000000007 ff800000000007ff febeffdfffefffff fffffffffffffffe")
        three_btn = daemon.parse_sysfs_bitmap("70000 0 0 0 0")
        self.assertTrue(m720 & (1 << daemon.BTN_LEFT))
        self.assertTrue(m720 & (1 << daemon.BTN_SIDE))
        self.assertTrue(m720 & daemon.EXTRA_BUTTON_MASK)
        self.assertTrue(three_btn & (1 << daemon.BTN_LEFT))
        self.assertFalse(three_btn & daemon.EXTRA_BUTTON_MASK)

    def test_rel_bitmap(self):
        rel = daemon.parse_sysfs_bitmap("1943")
        self.assertTrue(rel & (1 << daemon.REL_X))
        self.assertTrue(rel & (1 << daemon.REL_WHEEL))
        self.assertTrue(rel & (1 << daemon.REL_WHEEL_HI_RES))


if __name__ == "__main__":
    unittest.main()
