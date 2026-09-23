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
        self.assertIn("load_timeout", cfg)  # 사용자가 값을 바꿔도 통과하도록 값 자체는 검사하지 않음

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
    """core.decide_buttons()는 이미 계산된 점수(float)만 받는 순수 판정 함수."""

    def test_all_soldout_is_soldout(self):
        state, available = core.decide_buttons(1.0, [1.0, 1.0, 1.0, 1.0], 0.9)
        self.assertEqual(state, "soldout")
        self.assertEqual(available, [])

    def test_one_button_available(self):
        state, available = core.decide_buttons(1.0, [1.0, 1.0, 0.2, 1.0], 0.9)
        self.assertEqual(state, "available")
        self.assertEqual(available, [2])

    def test_multiple_available_returns_priority_order(self):
        # 1번(인덱스 0)과 3번(인덱스 2)이 동시에 매진 아님 -> 앞 번호부터 오름차순으로 반환
        state, available = core.decide_buttons(1.0, [0.2, 1.0, 0.3, 1.0], 0.9)
        self.assertEqual(state, "available")
        self.assertEqual(available, [0, 2])

    def test_anchor_invalid_is_unknown_regardless_of_buttons(self):
        state, available = core.decide_buttons(0.1, [0.2, 0.2, 0.2, 0.2], 0.9)
        self.assertEqual(state, "unknown")
        self.assertEqual(available, [])

    def test_screen_smaller_than_template(self):
        tpl = make_button("14:30")
        self.assertEqual(core.match_score(np.zeros((5, 5), np.uint8), tpl), 0.0)


class CheckButtonsTests(unittest.TestCase):
    """core.check_buttons()는 화면 캡처(core.grab_gray)를 실제 이미지 비교(match_score)와 연결하는 부분.
    버튼마다 크기/글자가 다를 수 있으므로 각자 자기 템플릿과만 비교해야 한다."""

    def setUp(self):
        # 버튼마다 서로 다른 "매진" 템플릿 (버튼 크기가 달라도 정확히 매칭되는지 확인하기 위함)
        self.soldout_tpls = [make_button(f"SOLD{i}") for i in range(4)]
        self.anchor_tpl = make_button("14:30")
        self.cfg = {
            "anchor_region": [0, 0, 10, 10],
            "button_regions": [[0, 0, 10, 10]] * 4,
            "search_padding": 0,
            "match_threshold": 0.9,
        }

    def test_one_button_available_end_to_end(self):
        # 버튼 3(인덱스 2)만 자기 템플릿("SOLD2")과 다른 글자("BOOK")가 나옴 -> 매진 아님
        screens = iter([embed(self.anchor_tpl)] + [
            embed(make_button(t)) for t in ("SOLD0", "SOLD1", "BOOK", "SOLD3")
        ])
        with mock.patch("core.grab_gray", side_effect=lambda region, pad=0: next(screens)):
            state, anchor, soldout_scores, available = core.check_buttons(self.cfg, self.soldout_tpls, self.anchor_tpl)
        self.assertEqual(state, "available")
        self.assertEqual(available, [2])
        self.assertEqual(len(soldout_scores), 4)
        self.assertGreaterEqual(anchor, 0.9)

    def test_all_match_own_template_is_soldout(self):
        screens = iter([embed(self.anchor_tpl)] + [
            embed(make_button(f"SOLD{i}")) for i in range(4)
        ])
        with mock.patch("core.grab_gray", side_effect=lambda region, pad=0: next(screens)):
            state, anchor, soldout_scores, available = core.check_buttons(self.cfg, self.soldout_tpls, self.anchor_tpl)
        self.assertEqual(state, "soldout")
        self.assertEqual(available, [])


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
