import unittest
from unittest import mock

import core
import watcher

BUTTON_REGIONS = [
    [100, 200, 50, 30],
    [160, 200, 50, 30],
    [220, 200, 50, 30],
    [280, 200, 50, 30],
]
RESERVE_REGION = [400, 500, 60, 40]


def make_cfg():
    cfg = core.load_config()
    cfg.update(anchor_region=[0, 0, 10, 10],
               button_regions=list(BUTTON_REGIONS),
               reserve_region=RESERVE_REGION,
               wait_seconds={"min": 0, "max": 0},
               second_click_delay={"min": 0, "max": 0})
    cfg["telegram"] = {"bot_token": "t", "chat_id": "1"}
    return cfg


def fake_result(state, available=None):
    """core.check_buttons()가 돌려주는 (state, anchor, soldout_scores, available) 형태로 맞춰줌."""
    available = available or []
    soldout_scores = [0.2 if i in available else 1.0 for i in range(4)]
    return state, 1.0, soldout_scores, available


class ButtonClickTests(unittest.TestCase):
    def run_flow(self, results):
        """results: [(state, available_idx_list), ...] 순서대로 판정이 나오도록 가짜로 돌림."""
        moves, clicks = [], []
        seq = iter(fake_result(*r) for r in results)
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True), \
                mock.patch("watcher.core.check_buttons", side_effect=lambda *a: next(seq)), \
                mock.patch("watcher.core.anchor_score", return_value=1.0), \
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

    def test_single_button_available_clicks_button_then_reserve(self):
        clicks, press, tg = self.run_flow([
            ("soldout", []), ("soldout", []), ("available", [2]), ("available", [2]),
        ])
        self.assertEqual(len(clicks), 2)
        self.assertTrue(self.inside(clicks[0], BUTTON_REGIONS[2]))  # 3번 버튼
        self.assertTrue(self.inside(clicks[1], RESERVE_REGION))
        self.assertEqual(tg.call_count, 1)
        self.assertEqual(press.call_count, 3)  # 매진 2회 + 가능 1회 = F5 3번

    def test_multiple_available_clicks_earliest_priority_button(self):
        clicks, _, _ = self.run_flow([
            ("available", [1, 3]), ("available", [1, 3]),
        ])
        self.assertEqual(len(clicks), 2)
        self.assertTrue(self.inside(clicks[0], BUTTON_REGIONS[1]))  # 2번이 4번보다 앞 순서라 우선
        self.assertTrue(self.inside(clicks[1], RESERVE_REGION))

    def test_no_click_when_recheck_says_not_available(self):
        clicks, _, tg = self.run_flow([
            ("available", [0]), ("soldout", []), ("available", [0]), ("available", [0]),
        ])
        self.assertEqual(len(clicks), 2)  # 첫 재확인 실패 후, 다음 라운드에서만 클릭
        self.assertEqual(tg.call_count, 1)

    def test_no_click_when_recheck_shows_target_button_soldout_again(self):
        # 처음엔 1번(인덱스0)이 매진 아님으로 보였다가, 재확인 시점엔 1번은 다시 매진 + 2번만 매진 아님
        # -> 노리던 1번은 여전히 매진이므로 이번 라운드는 클릭 안 함
        clicks, _, _ = self.run_flow([
            ("available", [0]), ("available", [1]), ("available", [0]), ("available", [0]),
        ])
        self.assertEqual(len(clicks), 2)
        self.assertTrue(self.inside(clicks[0], BUTTON_REGIONS[0]))


POPUP_REGION = [500, 600, 40, 20]


class PopupTests(unittest.TestCase):
    """(선택 기능) 예약 버튼 클릭 후 안내 팝업이 뜨면 확인 버튼까지 누르는지 확인."""

    def run_flow(self, popup_detected):
        moves, clicks = [], []
        seq = iter([fake_result("available", [0]), fake_result("available", [0])])
        cfg = make_cfg()
        cfg["popup_anchor_region"] = [900, 900, 10, 10]
        cfg["popup_confirm_region"] = POPUP_REGION
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True), \
                mock.patch("watcher.core.check_buttons", side_effect=lambda *a: next(seq)), \
                mock.patch("watcher.core.anchor_score", return_value=1.0), \
                mock.patch("watcher.core.check_popup", return_value=popup_detected), \
                mock.patch("watcher.core.interruptible_sleep"), \
                mock.patch("watcher.time.sleep"), \
                mock.patch("watcher.pyautogui.press"), \
                mock.patch("watcher.pyautogui.moveTo", side_effect=lambda x, y, **k: moves.append((x, y))), \
                mock.patch("watcher.pyautogui.click", side_effect=lambda: clicks.append(moves[-1])), \
                mock.patch("watcher.core.send_telegram", return_value=True), \
                mock.patch("watcher.say"):
            watcher.run(cfg, None, None, popup_tpl=object())
        return clicks

    def inside(self, point, region):
        l, t, w, h = region
        return l <= point[0] < l + w and t <= point[1] < t + h

    def test_clicks_confirm_when_popup_detected(self):
        clicks = self.run_flow(popup_detected=True)
        self.assertEqual(len(clicks), 3)  # 버튼 + 예약 + 팝업 확인
        self.assertTrue(self.inside(clicks[2], POPUP_REGION))

    def test_no_extra_click_when_popup_not_detected(self):
        clicks = self.run_flow(popup_detected=False)
        self.assertEqual(len(clicks), 2)  # 버튼 + 예약만


class OrderTests(unittest.TestCase):
    def test_order_f5_then_judge_then_random_wait_then_f5(self):
        events = []
        seq = iter([fake_result("soldout"), fake_result("available", [0]), fake_result("available", [0])])
        cfg = make_cfg()
        cfg["load_check_interval"] = 0.5
        cfg["after_load_delay"] = {"min": 1, "max": 1}
        cfg["wait_seconds"] = {"min": 33, "max": 33}
        cfg["recheck_delay"] = 7
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True), \
                mock.patch("watcher.core.check_buttons", side_effect=lambda *a: (events.append("판단"), next(seq))[1]), \
                mock.patch("watcher.core.anchor_score", side_effect=lambda *a: (events.append("기준칸"), 1.0)[1]), \
                mock.patch("watcher.core.interruptible_sleep", side_effect=lambda s: events.append(f"대기{s:g}")), \
                mock.patch("watcher.time.sleep"), \
                mock.patch("watcher.pyautogui.press", side_effect=lambda k: events.append("F5")), \
                mock.patch("watcher.pyautogui.moveTo"), mock.patch("watcher.pyautogui.click"), \
                mock.patch("watcher.core.send_telegram", return_value=True), mock.patch("watcher.say"):
            watcher.run(cfg, None, None)
        # 매진이면: F5 -> 0.5초 -> 기준칸 확인(보임) -> 1초 -> 판단 -> 33초 -> F5 -> ... -> 판단(가능) -> 7초 -> 재확인
        self.assertEqual(events[:12], ["F5", "대기0.5", "기준칸", "대기1", "판단", "대기33",
                                       "F5", "대기0.5", "기준칸", "대기1", "판단", "대기7"])


class LoadWaitTests(unittest.TestCase):
    """F5 뒤 기준 칸이 보일 때까지 0.5초마다 확인하는 부분."""

    def run_flow(self, anchor_scores, results):
        events, clock = [], [0.0]

        def fake_sleep(s):
            clock[0] += s
            events.append(f"대기{s:g}")

        scores = iter(anchor_scores)
        seq = iter(fake_result(*r) for r in results)
        cfg = make_cfg()
        cfg["after_load_delay"] = {"min": 1, "max": 1}
        with mock.patch("watcher.core.is_chrome_foreground", return_value=True), \
                mock.patch("watcher.core.anchor_score", side_effect=lambda *a: (events.append("기준칸"), next(scores))[1]), \
                mock.patch("watcher.core.check_buttons", side_effect=lambda *a: (events.append("판단"), next(seq))[1]), \
                mock.patch("watcher.core.interruptible_sleep", side_effect=fake_sleep), \
                mock.patch("watcher.time.monotonic", side_effect=lambda: clock[0]), \
                mock.patch("watcher.time.sleep"), \
                mock.patch("watcher.pyautogui.press", side_effect=lambda k: events.append("F5")), \
                mock.patch("watcher.pyautogui.moveTo"), mock.patch("watcher.pyautogui.click"), \
                mock.patch("watcher.core.send_telegram", return_value=True) as tg, \
                mock.patch("watcher.say"):
            watcher.run(cfg, None, None)
        return events, tg

    def test_checks_again_every_half_second_until_anchor_visible(self):
        events, _ = self.run_flow([0.1, 0.17, 1.0], [("available", [0]), ("available", [0])])
        # 안 보임 -> 0.5초 뒤 다시 -> 안 보임 -> 0.5초 뒤 다시 -> 보임 -> 1초 -> 판단
        self.assertEqual(events[:9], ["F5", "대기0.5", "기준칸", "대기0.5", "기준칸",
                                      "대기0.5", "기준칸", "대기1", "판단"])

    def test_telegram_and_stop_when_not_visible_for_60_seconds(self):
        events, tg = self.run_flow([0.1] * 1000, [])
        self.assertNotIn("판단", events)  # 화면이 안 떴으니 매진 판단은 하지 않음
        self.assertEqual(events.count("F5"), 1)  # 다시 F5 누르지 않고 멈춤
        self.assertEqual(events.count("기준칸"), 120)  # 0.5초마다 60초 = 120번 확인
        self.assertEqual(tg.call_count, 1)
        self.assertIn("60초", tg.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
