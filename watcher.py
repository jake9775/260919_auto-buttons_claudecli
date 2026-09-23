"""메인 프로그램: F5 → 화면이 뜰 때까지 확인 → 매진 판단 → (가능하면) 클릭 + 텔레그램 알림.

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
    missing_buttons = len(cfg["button_regions"]) != 4 or any(not r for r in cfg["button_regions"])
    missing_imgs = not all(p.exists() for p in core.SOLDOUT_IMGS) or not core.ANCHOR_IMG.exists()
    if not cfg["anchor_region"] or missing_buttons or missing_imgs:
        sys.exit("먼저 'python setup_capture.py'로 준비 작업을 해 주세요.")
    if not cfg["reserve_region"]:
        sys.exit("예약 버튼 영역이 아직 없습니다. 'python setup_capture.py --reserve-click'을 실행해 주세요.")


def click_random_point(cfg, region):
    x, y = core.random_point(region)
    pyautogui.moveTo(x, y, duration=core.rand_between(cfg["mouse_move_duration"]), tween=pyautogui.easeOutQuad)
    time.sleep(core.rand_between(cfg["pre_click_pause"]))
    pyautogui.click()
    return x, y


def dry_run(cfg, soldout_tpls, anchor_tpl):
    say(f"연습 실행: F5/클릭/알림 없이 {cfg['dry_run_interval']}초마다 판정만 보여줍니다. (Esc로 종료)")
    while True:
        state, anchor, soldout_scores, available = core.check_buttons(cfg, soldout_tpls, anchor_tpl)
        scores_txt = ", ".join(f"{i + 1}번={s:.2f}" for i, s in enumerate(soldout_scores))
        extra = f" → 매진 아님: {[i + 1 for i in available]}번" if state == "available" else ""
        say(f"판정={state}  (기준칸 일치도={anchor:.2f}, 버튼별 매진 일치도: {scores_txt}){extra}")
        core.interruptible_sleep(cfg["dry_run_interval"])


def wait_before_next_f5(cfg, round_no):
    wait = core.pick_wait(cfg)
    say(f"#{round_no} {wait:.3f}초 뒤 다시 F5")
    core.interruptible_sleep(wait)


def wait_page_loaded(cfg, anchor_tpl, round_no):
    """F5 뒤 load_check_interval마다 기준 칸을 확인. 보이면 after_load_delay만큼 더 기다리고 True,
    load_timeout이 지나도 안 보이면 False."""
    deadline = time.monotonic() + cfg["load_timeout"]
    while True:
        core.interruptible_sleep(cfg["load_check_interval"])
        score = core.anchor_score(cfg, anchor_tpl)
        if score >= cfg["match_threshold"]:
            break
        if time.monotonic() >= deadline:
            return False
    wait = core.rand_between(cfg["after_load_delay"])
    say(f"#{round_no} 화면 뜸 (기준칸 {score:.2f}) → {wait:.3f}초 뒤 판단")
    core.interruptible_sleep(wait)
    return True


def popup_enabled(cfg):
    return bool(cfg["popup_anchor_region"] and cfg["popup_confirm_region"] and core.POPUP_IMG.exists())


def handle_popup(cfg, popup_tpl):
    """(선택 기능) 예약 버튼을 누른 뒤 안내 팝업이 떴으면 '확인'까지 눌러줌."""
    core.interruptible_sleep(cfg["popup_check_delay"])
    if not core.check_popup(cfg, popup_tpl):
        return
    x, y = click_random_point(cfg, cfg["popup_confirm_region"])
    say(f"안내 팝업 감지 → 확인 버튼 ({x}, {y}) 클릭")


def run(cfg, soldout_tpls, anchor_tpl, popup_tpl=None):
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
            say(f"#{round_no} F5 누름 → 화면이 뜨는지 {cfg['load_check_interval']}초마다 확인")
            if not wait_page_loaded(cfg, anchor_tpl, round_no):
                say(f"#{round_no} F5 후 {cfg['load_timeout']}초가 지나도 화면이 뜨지 않아 다시 F5")
                continue
            state, anchor, _, available = core.check_buttons(cfg, soldout_tpls, anchor_tpl)
            say(f"#{round_no} 판정={state} (기준칸 {anchor:.2f})")
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

        # available: 여러 버튼이 동시에 풀렸으면 번호가 가장 빠른 것을 우선
        target_idx = available[0]
        avail_nums = ", ".join(f"{i + 1}번" for i in available)
        say(f"#{round_no} 매진 아닌 버튼: {avail_nums} → {target_idx + 1}번 우선 클릭 예정, 재확인 중")

        # 화면이 넘어가는 중일 수 있으니 잠시 뒤 그 버튼만 한 번 더 확인
        core.interruptible_sleep(cfg["recheck_delay"])
        state2, _, soldout_scores2, available2 = core.check_buttons(cfg, soldout_tpls, anchor_tpl)
        still_available = state2 == "available" and soldout_scores2[target_idx] < cfg["match_threshold"]
        if not still_available:
            say("재확인에서 예약 가능이 아니어서 계속 감시합니다.")
            wait_before_next_f5(cfg, round_no)
            continue

        avail_nums2 = ", ".join(f"{i + 1}번" for i in available2) if available2 else f"{target_idx + 1}번"
        x, y = click_random_point(cfg, cfg["button_regions"][target_idx])
        say(f"{target_idx + 1}번 버튼 예약 가능! (매진 아닌 버튼: {avail_nums2}) ({x}, {y}) 클릭")
        core.interruptible_sleep(core.rand_between(cfg["second_click_delay"]))
        x2, y2 = click_random_point(cfg, cfg["reserve_region"])
        say(f"예약 버튼 ({x2}, {y2}) 클릭")

        if popup_tpl is not None:
            handle_popup(cfg, popup_tpl)

        ok = core.send_telegram(cfg, f"🚄 {target_idx + 1}번 버튼 예약 가능해 보입니다! (매진 아닌 버튼: {avail_nums2}) 두 영역을 클릭했습니다. 지금 크롬 화면을 확인하세요. ({datetime.now():%H:%M:%S})")
        say("텔레그램 알림 전송 " + ("성공" if ok else "실패"))
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = core.load_config()
    validate(cfg)
    soldout_tpls = [core.load_gray(p) for p in core.SOLDOUT_IMGS]
    anchor_tpl = core.load_gray(core.ANCHOR_IMG)
    popup_tpl = core.load_gray(core.POPUP_IMG) if popup_enabled(cfg) else None
    if popup_tpl is not None:
        say("안내 팝업 확인 기능이 켜져 있습니다 (예약 버튼 클릭 후 자동으로 '확인'까지 누름).")

    say(f"{cfg['start_delay']}초 뒤에 시작합니다. 크롬 예매 화면을 맨 앞에 두세요. (Esc로 중지)")
    core.interruptible_sleep(cfg["start_delay"])

    try:
        if args.dry_run:
            dry_run(cfg, soldout_tpls, anchor_tpl)
        else:
            run(cfg, soldout_tpls, anchor_tpl, popup_tpl)
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
