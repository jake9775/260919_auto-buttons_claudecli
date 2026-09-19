"""메인 프로그램: F5 → 랜덤 대기 → 매진 판단 → (가능하면) 클릭 + 텔레그램 알림.

사용법:
    python watcher.py            실제 실행
    python watcher.py --dry-run  연습 실행 (F5/클릭/알림 없이 판정만 화면에 출력)
멈추기: Esc 키, 또는 마우스를 화면 모서리로 밀기.
"""
import argparse
import logging
import sys
import time
from datetime import datetime

import pyautogui

import core

logging.basicConfig(
    filename=str(core.BASE / "watcher.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    encoding="utf-8",
)


def say(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    logging.info(msg)


def validate(cfg):
    errors = core.timing_errors(cfg)
    if errors:
        sys.exit("시간설정.json을 확인해 주세요:\n- " + "\n- ".join(errors))
    missing = [k for k in ("soldout_region", "anchor_region", "click_region") if not cfg[k]]
    if missing or not core.SOLDOUT_IMG.exists() or not core.ANCHOR_IMG.exists():
        sys.exit("먼저 'python setup_capture.py'로 준비 작업을 해 주세요.")
    if not cfg["click_region2"]:
        sys.exit("두 번째 클릭 영역이 아직 없습니다. 'python setup_capture.py --second-click'을 실행해 주세요.")


def click_random_point(cfg, region):
    x, y = core.random_point(region)
    pyautogui.moveTo(x, y, duration=core.rand_between(cfg["mouse_move_duration"]), tween=pyautogui.easeOutQuad)
    time.sleep(core.rand_between(cfg["pre_click_pause"]))
    pyautogui.click()
    return x, y


def dry_run(cfg, soldout_tpl, anchor_tpl):
    say(f"연습 실행: F5/클릭/알림 없이 {cfg['dry_run_interval']}초마다 판정만 보여줍니다. (Esc로 종료)")
    while True:
        state, anchor, soldout = core.check_screen(cfg, soldout_tpl, anchor_tpl)
        say(f"판정={state}  (기준칸 일치도={anchor:.2f}, 매진칸 일치도={soldout:.2f})")
        core.interruptible_sleep(cfg["dry_run_interval"])


def wait_before_next_f5(cfg, round_no):
    wait = core.pick_wait(cfg)
    say(f"#{round_no} {wait:.3f}초 뒤 다시 F5")
    core.interruptible_sleep(wait)


def run(cfg, soldout_tpl, anchor_tpl):
    unknown_in_row = 0
    round_no = 0
    while True:
        round_no += 1
        if not core.is_chrome_foreground():
            say(f"#{round_no} 크롬이 맨 앞 창이 아니라서 F5를 누르지 않았습니다. (현재: {core.foreground_title()!r})")
            state = "unknown"
            core.interruptible_sleep(cfg["chrome_retry_delay"])
            refreshed = False
        else:
            pyautogui.press("f5")
            say(f"#{round_no} F5 누름 → {cfg['judge_delay']}초 뒤 판단")
            core.interruptible_sleep(cfg["judge_delay"])
            state, anchor, soldout = core.check_screen(cfg, soldout_tpl, anchor_tpl)
            say(f"#{round_no} 판정={state} (기준칸 {anchor:.2f}, 매진칸 {soldout:.2f})")
            refreshed = True

        if state == "soldout":
            unknown_in_row = 0
            wait_before_next_f5(cfg, round_no)
            continue

        if state == "unknown":
            unknown_in_row += 1
            if unknown_in_row >= cfg["max_unknown_in_row"]:
                core.send_telegram(cfg, "⚠️ 기차표 감시 중단: 화면 상태를 알 수 없습니다. "
                                        "로그인/오류창/창 위치를 확인해 주세요.")
                say("화면 판단 불가가 계속되어 중지합니다.")
                return
            if refreshed:  # 크롬이 앞에 없어서 F5를 안 눌렀을 때는 chrome_retry_delay만 쉬고 바로 재시도
                wait_before_next_f5(cfg, round_no)
            continue

        # available: 화면이 넘어가는 중일 수 있으니 잠시 뒤 한 번 더 확인
        core.interruptible_sleep(cfg["recheck_delay"])
        state2, _, _ = core.check_screen(cfg, soldout_tpl, anchor_tpl)
        if state2 != "available":
            say("재확인에서 예약 가능이 아니어서 계속 감시합니다.")
            wait_before_next_f5(cfg, round_no)
            continue

        x, y = click_random_point(cfg, cfg["click_region"])
        say(f"예약 가능! 1번 영역 ({x}, {y}) 클릭")
        core.interruptible_sleep(core.rand_between(cfg["second_click_delay"]))
        x2, y2 = click_random_point(cfg, cfg["click_region2"])
        say(f"2번 영역 ({x2}, {y2}) 클릭")
        ok = core.send_telegram(cfg, f"🚄 예약 가능해 보입니다! 두 영역을 클릭했습니다. 지금 크롬 화면을 확인하세요. ({datetime.now():%H:%M:%S})")
        say("텔레그램 알림 전송 " + ("성공" if ok else "실패"))
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = core.load_config()
    validate(cfg)
    soldout_tpl = core.load_gray(core.SOLDOUT_IMG)
    anchor_tpl = core.load_gray(core.ANCHOR_IMG)

    say(f"{cfg['start_delay']}초 뒤에 시작합니다. 크롬 예매 화면을 맨 앞에 두세요. (Esc로 중지)")
    core.interruptible_sleep(cfg["start_delay"])

    try:
        (dry_run if args.dry_run else run)(cfg, soldout_tpl, anchor_tpl)
    except core.StopRequested:
        say("Esc가 눌려 중지했습니다.")
    except pyautogui.FailSafeException:
        say("마우스가 화면 모서리에 닿아 중지했습니다.")
    except Exception as e:  # 예상 못한 오류: 자리를 비웠을 때를 위해 알림
        logging.exception("오류")
        core.send_telegram(cfg, f"⚠️ 기차표 감시 프로그램이 오류로 멈췄습니다: {e}")
        raise


if __name__ == "__main__":
    main()
