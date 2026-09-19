import unittest
from unittest import mock

import core
import watcher

REGION1 = [100, 200, 50, 30]
REGION2 = [400, 500, 60, 40]


def make_cfg():
    cfg = core.load_config()
    cfg.update(soldout_region=[0, 0, 10, 10], anchor_region=[0, 0, 10, 10],
               click_region=REGION1, click_region2=REGION2,
               wait_seconds={"min": 0, "max": 0},
               second_click_delay={"min": 0, "max": 0})
    cfg["telegram"] = {"bot_token": "t", "chat_id": "1"}
    return cfg


class TwoClickTests(unittest.TestCase):
    def run_flow(self, states):
        """states 순서대로 화면 판정이 나오도록 가짜로 돌리고, 클릭 위치들을 돌려줌."""
        moves, clicks = [], []
        seq = iter(states)
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True), \
                mock.patch("watcher.core.check_screen", side_effect=lambda *a: (next(seq), 1.0, 1.0)), \
                mock.patch("watcher.core.interruptible_sleep"), \
                mock.patch("watcher.time.sleep"), \
                mock.patch("watcher.pyautogui.press") as press, \
                mock.patch("watcher.pyautogui.moveTo", side_effect=lambda x, y, **k: moves.append((x, y))), \
                mock.patch("watcher.pyautogui.click", side_effect=lambda: clicks.append(moves[-1])), \
                mock.patch("watcher.core.send_telegram", return_value=True) as tg, \
                mock.patch("watcher.say"):
            watcher.run(make_cfg(), None, None)
        return clicks, press, tg

    def inside(self, point, region):
        l, t, w, h = region
        return l <= point[0] < l + w and t <= point[1] < t + h

    def test_available_clicks_region1_then_region2_then_notifies_once(self):
        clicks, press, tg = self.run_flow(["soldout", "soldout", "available", "available"])
        self.assertEqual(len(clicks), 2)
        self.assertTrue(self.inside(clicks[0], REGION1))
        self.assertTrue(self.inside(clicks[1], REGION2))
        self.assertEqual(tg.call_count, 1)
        self.assertEqual(press.call_count, 3)  # 매진 2회 + 가능 1회 = F5 3번

    def test_order_f5_then_judge_then_random_wait_then_f5(self):
        events = []
        seq = iter(["soldout", "available", "available"])
        cfg = make_cfg()
        cfg["judge_delay"] = 2
        cfg["wait_seconds"] = {"min": 33, "max": 33}
        cfg["recheck_delay"] = 7
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True),                 mock.patch("watcher.core.check_screen", side_effect=lambda *a: (events.append("판단"), (next(seq), 1.0, 1.0))[1]),                 mock.patch("watcher.core.interruptible_sleep", side_effect=lambda s: events.append(f"대기{s:g}")),                 mock.patch("watcher.time.sleep"),                 mock.patch("watcher.pyautogui.press", side_effect=lambda k: events.append("F5")),                 mock.patch("watcher.pyautogui.moveTo"), mock.patch("watcher.pyautogui.click"),                 mock.patch("watcher.core.send_telegram", return_value=True), mock.patch("watcher.say"):
            watcher.run(cfg, None, None)
        # 매진이면: F5 -> 2초 -> 판단 -> 33초 -> F5 -> 2초 -> 판단(가능) -> 7초 -> 재확인
        self.assertEqual(events[:8], ["F5", "대기2", "판단", "대기33", "F5", "대기2", "판단", "대기7"])

    def test_no_click_when_recheck_says_not_available(self):
        clicks, _, tg = self.run_flow(["available", "soldout", "available", "available"])
        self.assertEqual(len(clicks), 2)  # 첫 재확인 실패 후, 다음 라운드에서만 클릭
        self.assertEqual(tg.call_count, 1)


if __name__ == "__main__":
    unittest.main()
