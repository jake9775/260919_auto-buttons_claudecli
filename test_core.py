import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import core

CFG = {"wait_seconds": {"min": 30, "max": 60},
       "telegram": {"bot_token": "tok", "chat_id": "123"}}


def make_button(text):
    img = np.full((40, 120), 255, dtype=np.uint8)
    if text:
        cv2.putText(img, text, (5, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    return img


def embed(template, pad=12, shift=(3, 4)):
    """template을 여백이 있는 더 큰 화면 안에 살짝 옮겨 넣음."""
    h, w = template.shape
    screen = np.full((h + 2 * pad, w + 2 * pad), 255, dtype=np.uint8)
    screen[pad + shift[0]:pad + shift[0] + h, pad + shift[1]:pad + shift[1] + w] = template
    return screen


class RandomTests(unittest.TestCase):
    def test_wait_within_range(self):
        for _ in range(1000):
            self.assertTrue(30 <= core.pick_wait(CFG) <= 60)

    def test_click_point_inside_region(self):
        region = [100, 200, 50, 30]
        for _ in range(2000):
            x, y = core.random_point(region)
            self.assertTrue(100 <= x <= 149 and 200 <= y <= 229)


class TimingSettingsTests(unittest.TestCase):
    def test_shipped_timing_file_is_valid_and_loaded(self):
        cfg = core.load_config()
        self.assertEqual(core.timing_errors(cfg), [])
        self.assertIn("judge_delay", cfg)  # 사용자가 값을 바꿔도 통과하도록 값 자체는 검사하지 않음

    def test_timing_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "시간설정.json"
            path.write_text('{"wait_seconds": {"min": 45, "max": 90}, "recheck_delay": 3}', encoding="utf-8")
            with mock.patch.object(core, "TIMING_PATH", path):
                cfg = core.load_config()
        self.assertEqual(cfg["wait_seconds"], {"min": 45, "max": 90})
        self.assertEqual(cfg["recheck_delay"], 3)
        self.assertEqual(cfg["start_delay"], 5)  # 안 적은 항목은 기본값 유지

    def test_min_greater_than_max_is_reported(self):
        cfg = core.load_config()
        cfg["wait_seconds"] = {"min": 60, "max": 30}
        self.assertTrue(any("wait_seconds" in e for e in core.timing_errors(cfg)))

    def test_negative_or_text_value_is_reported(self):
        cfg = core.load_config()
        cfg["recheck_delay"] = -1
        cfg["start_delay"] = "abc"
        self.assertEqual(len(core.timing_errors(cfg)), 2)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.soldout_tpl = make_button("SOLD")
        self.anchor_tpl = make_button("14:30")

    def score(self, screen, tpl):
        return core.match_score(screen, tpl)

    def test_soldout_screen_detected(self):
        a = self.score(embed(self.anchor_tpl), self.anchor_tpl)
        s = self.score(embed(self.soldout_tpl), self.soldout_tpl)
        self.assertEqual(core.decide(a, s, 0.9), "soldout")

    def test_available_screen_detected(self):
        a = self.score(embed(self.anchor_tpl), self.anchor_tpl)
        s = self.score(embed(make_button("BOOK")), self.soldout_tpl)
        self.assertEqual(core.decide(a, s, 0.9), "available")

    def test_wrong_page_is_unknown(self):
        blank = np.full((64, 144), 255, dtype=np.uint8)
        a = self.score(blank, self.anchor_tpl)
        s = self.score(blank, self.soldout_tpl)
        self.assertEqual(core.decide(a, s, 0.9), "unknown")

    def test_screen_smaller_than_template(self):
        self.assertEqual(core.match_score(np.zeros((5, 5), np.uint8), self.anchor_tpl), 0.0)


class TelegramTests(unittest.TestCase):
    def test_success(self):
        with mock.patch("core.requests.post", return_value=mock.Mock(status_code=200)) as post:
            self.assertTrue(core.send_telegram(CFG, "hi"))
            self.assertEqual(post.call_count, 1)

    def test_retries_then_fails(self):
        with mock.patch("core.requests.post", return_value=mock.Mock(status_code=500)) as post, \
                mock.patch("core.time.sleep"):
            self.assertFalse(core.send_telegram(CFG, "hi"))
            self.assertEqual(post.call_count, 3)

    def test_no_credentials_does_not_send(self):
        cfg = {"telegram": {"bot_token": "", "chat_id": ""}}
        with mock.patch("core.requests.post") as post:
            self.assertFalse(core.send_telegram(cfg, "hi"))
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
