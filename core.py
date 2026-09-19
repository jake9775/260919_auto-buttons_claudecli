"""공통 기능: 설정 저장/불러오기, 화면 캡처와 비교, 랜덤 값, 텔레그램 전송."""
import ctypes
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui
import requests

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
SOLDOUT_IMG = BASE / "ref_soldout.png"  # "매진" 상태일 때의 버튼 칸 그림
ANCHOR_IMG = BASE / "ref_anchor.png"    # 열차 시간 등 항상 보여야 하는 칸 그림

TIMING_PATH = BASE / "시간설정.json"  # 시간 관련 값은 전부 이 파일에서만 읽음

# 시간설정.json 이 없거나 항목이 빠졌을 때 쓰는 기본값
DEFAULT_TIMING = {
    "start_delay": 5,
    "judge_delay": 2,
    "wait_seconds": {"min": 30, "max": 60},
    "recheck_delay": 2,
    "mouse_move_duration": {"min": 0.4, "max": 1.0},
    "pre_click_pause": {"min": 0.1, "max": 0.3},
    "second_click_delay": {"min": 0.5, "max": 1.5},
    "chrome_retry_delay": 5,
    "dry_run_interval": 3,
    "capture_delay": 5,
}

DEFAULT_CONFIG = {
    "telegram": {"bot_token": "", "chat_id": ""},
    "soldout_region": None,  # [왼쪽, 위, 너비, 높이]
    "anchor_region": None,
    "click_region": None,
    "click_region2": None,  # 첫 클릭 뒤에 이어서 누를 두 번째 영역
    "match_threshold": 0.9,
    "max_unknown_in_row": 5,
    "search_padding": 12,  # 화면이 살짝 움직여도 찾을 수 있게 넓히는 여유(픽셀)
}

VK_ESCAPE = 0x1B


class StopRequested(Exception):
    """사용자가 Esc를 눌러 멈춤."""


# ---------- 설정 ----------
def _merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value


def load_config():
    """config.json(영역/텔레그램) + 시간설정.json(시간)을 합쳐서 불러옴."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        # 예전 버전이 config.json에 저장해 둔 시간 값은 무시 (시간설정.json이 유일한 기준)
        _merge(cfg, {k: v for k, v in saved.items() if k not in DEFAULT_TIMING})
    cfg.update(json.loads(json.dumps(DEFAULT_TIMING)))
    if TIMING_PATH.exists():
        _merge(cfg, json.loads(TIMING_PATH.read_text(encoding="utf-8")))
    return cfg


def save_config(cfg):
    to_save = {k: v for k, v in cfg.items() if k not in DEFAULT_TIMING}
    CONFIG_PATH.write_text(json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8")


def timing_errors(cfg):
    """시간 설정에 잘못된 값이 있으면 한국어 오류 문장 목록을 돌려줌."""
    errors = []
    for key, default in DEFAULT_TIMING.items():
        value = cfg[key]
        if isinstance(default, dict):
            if not isinstance(value, dict) or not all(isinstance(value.get(k), (int, float)) for k in ("min", "max")):
                errors.append(f"'{key}'에는 min과 max 숫자가 모두 있어야 합니다.")
            elif value["min"] < 0 or value["min"] > value["max"]:
                errors.append(f"'{key}': min은 0 이상이고 max보다 작거나 같아야 합니다. (지금 min={value['min']}, max={value['max']})")
        elif not isinstance(value, (int, float)) or value < 0:
            errors.append(f"'{key}'에는 0 이상의 숫자를 넣어야 합니다. (지금 {value!r})")
    return errors


# ---------- 랜덤 ----------
def rand_between(rng):
    """{'min': a, 'max': b} 범위에서 무작위 숫자 하나."""
    return random.uniform(rng["min"], rng["max"])


def pick_wait(cfg):
    return rand_between(cfg["wait_seconds"])


def random_point(region):
    left, top, width, height = region
    return random.randint(left, left + width - 1), random.randint(top, top + height - 1)


# ---------- 키보드/창 상태 (Windows) ----------
def esc_pressed():
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)


def foreground_title():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def is_chrome_foreground():
    return "Chrome" in foreground_title()


def interruptible_sleep(seconds):
    """대기 중에도 Esc를 누르면 바로 멈춤."""
    end = time.time() + seconds
    while time.time() < end:
        if esc_pressed():
            raise StopRequested()
        time.sleep(0.2)


# ---------- 화면 비교 ----------
def grab_gray(region, pad=0):
    left, top, width, height = region
    left, top = max(0, left - pad), max(0, top - pad)
    img = pyautogui.screenshot(region=(left, top, width + 2 * pad, height + 2 * pad))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def load_gray(path):
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def match_score(screen_gray, template_gray):
    """template 그림이 screen 안 어딘가에 있으면 1에 가까운 값 (0~1)."""
    sh, sw = screen_gray.shape[:2]
    th, tw = template_gray.shape[:2]
    if sh < th or sw < tw:
        return 0.0
    result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    return float(np.nan_to_num(result.max(), nan=0.0, posinf=0.0, neginf=0.0))


def decide(anchor_score, soldout_score, threshold):
    """판정: 'unknown'(화면이 이상함) / 'soldout'(매진) / 'available'(예약 가능 추정)."""
    if anchor_score < threshold:
        return "unknown"
    if soldout_score >= threshold:
        return "soldout"
    return "available"


def check_screen(cfg, soldout_tpl, anchor_tpl):
    pad = cfg["search_padding"]
    anchor = match_score(grab_gray(cfg["anchor_region"], pad), anchor_tpl)
    soldout = match_score(grab_gray(cfg["soldout_region"], pad), soldout_tpl)
    return decide(anchor, soldout, cfg["match_threshold"]), anchor, soldout


# ---------- 텔레그램 ----------
def send_telegram(cfg, text, retries=3):
    token, chat_id = cfg["telegram"]["bot_token"], cfg["telegram"]["chat_id"]
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(retries):
        try:
            r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(2)
    return False


def find_chat_id(token):
    """봇에게 보낸 마지막 메시지에서 채팅 ID를 찾음. 못 찾으면 None."""
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    r.raise_for_status()
    for update in reversed(r.json().get("result", [])):
        msg = update.get("message") or update.get("channel_post")
        if msg:
            return str(msg["chat"]["id"])
    return None
