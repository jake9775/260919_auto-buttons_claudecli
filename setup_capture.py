"""처음 한 번만 실행: 텔레그램 연결과 화면 영역 지정."""
import sys
import time

import cv2
import numpy as np
import pyautogui

import core


def countdown(message, seconds=6):
    print(f"\n{message}")
    for s in range(seconds, 0, -1):
        print(f"  {s}초 뒤에 마우스 위치를 기록합니다...", end="\r")
        time.sleep(1)
    pos = pyautogui.position()
    print(f"  기록됨: x={pos.x}, y={pos.y}            ")
    return pos.x, pos.y


def pick_region(name, hint):
    print(f"\n===== [{name}] 지정 =====")
    print(hint)
    while True:
        x1, y1 = countdown("마우스를 사각형의 '왼쪽 위 모서리'에 올려두세요.")
        x2, y2 = countdown("이번에는 '오른쪽 아래 모서리'에 올려두세요.")
        left, top = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        if width >= 5 and height >= 5:
            return [left, top, width, height]
        print("사각형이 너무 작습니다. 다시 지정합니다.")


def setup_telegram(cfg):
    print("\n===== 텔레그램 연결 =====")
    token = input("BotFather에서 받은 봇 토큰을 붙여넣고 Enter: ").strip()
    input("텔레그램에서 방금 만든 봇을 찾아 '안녕'이라고 메시지를 보낸 뒤, 여기서 Enter: ")
    chat_id = core.find_chat_id(token)
    if not chat_id:
        print("봇에게 온 메시지를 찾지 못했습니다. 메시지를 보냈는지 확인하고 다시 실행해 주세요.")
        return False
    cfg["telegram"] = {"bot_token": token, "chat_id": chat_id}
    if core.send_telegram(cfg, "✅ 기차표 알림 연결 성공! 이 메시지가 보이면 정상입니다."):
        print("텔레그램으로 테스트 메시지를 보냈습니다. 폰을 확인해 보세요.")
        return True
    print("테스트 메시지 전송에 실패했습니다. 토큰을 다시 확인해 주세요.")
    return False


def pick_reserve_click(cfg):
    cfg["reserve_region"] = pick_region(
        "예약 버튼 영역",
        "매진 아닌 버튼을 클릭한 뒤 이어서 누를 '예약' 버튼(화면 오른쪽 아래 등)을 감쌉니다.",
    )
    core.save_config(cfg)
    print("\n✅ 예약 버튼 영역 저장 완료.")


def capture_templates(cfg):
    """이미 지정된 영역(anchor_region/button_regions) 그대로, 그림만 다시 찍어서 저장."""
    print(f"\n{cfg['capture_delay']}초 뒤에 화면을 캡처합니다. 그동안 크롬 화면을 버튼 4개 전부 '매진' 상태로 두고,")
    print("검은 창이 지정한 영역을 가리지 않는지 확인하세요.")
    for s in range(cfg["capture_delay"], 0, -1):
        print(f"  {s}초 뒤 캡처...", end="\r", flush=True)
        time.sleep(1)
    print("  캡처합니다!            ")

    shots = [(core.ANCHOR_IMG, cfg["anchor_region"])]
    shots += list(zip(core.SOLDOUT_IMGS, cfg["button_regions"]))
    for path, region in shots:
        shot = np.array(pyautogui.screenshot(region=tuple(region)))
        cv2.imwrite(str(path), cv2.cvtColor(shot, cv2.COLOR_RGB2BGR))

    print("\n✅ 저장 완료. 저장된 그림(ref_soldout_1~4.png, ref_anchor.png)을 열어서")
    print("   버튼 1~4번의 '매진' 칸과 '기준 칸'이 제대로 찍혔는지 확인해 보세요.")
    print("   다음 단계: python watcher.py --dry-run  (연습 실행)")


def main():
    cfg = core.load_config()

    if "--reserve-click" in sys.argv:
        print("[안내] '예약' 버튼이 보이도록 크롬을 준비하세요.")
        print("       (검은 창이 그 위치를 가리지 않게 구석으로 옮겨 두세요.)")
        input("준비되면 Enter: ")
        pick_reserve_click(cfg)
        return

    if "--recapture" in sys.argv:
        missing = not cfg["anchor_region"] or len(cfg["button_regions"]) != 4 or any(not r for r in cfg["button_regions"])
        if missing:
            print("아직 영역이 다 지정되지 않았습니다. 먼저 'python setup_capture.py'를 한 번 실행해 주세요.")
            return
        print("[안내] 영역 위치는 그대로 두고, 그림만 다시 찍습니다.")
        print("       크롬에서 버튼 4개가 전부 '매진'으로 보이는 화면을 준비하세요.")
        input("준비되면 Enter: ")
        capture_templates(cfg)
        return

    if input("텔레그램 연결부터 할까요? (y/n): ").strip().lower() == "y":
        if not setup_telegram(cfg):
            return
        core.save_config(cfg)

    print("\n[준비] 크롬에서 감시할 열차 줄의 버튼 4개가 모두 '매진'으로 보이는 예매 화면을 열어 두세요.")
    print("[참고] 버튼 4개는 보통 열차·좌석 조합입니다 (예: 열차1 일반실/특실, 열차2 일반실/특실).")
    print("[주의] 이 검은 창이 아래에 지정할 영역을 가리지 않도록 화면 구석에 옮겨 두세요.")
    input("준비되면 Enter: ")

    cfg["anchor_region"] = pick_region(
        "1. 기준 칸",
        "출발 시간처럼 항상 똑같이 보이는 글자 부분을 감쌉니다.\n"
        "(화면이 정상인지 확인하는 용도입니다.)",
    )

    cfg["button_regions"] = []
    for i in range(1, 5):
        region = pick_region(
            f"{i + 1}. 버튼 {i}번 ('매진' 칸)",
            f"{i}번째로 확인할 버튼(열차·좌석 조합)의 '매진' 글자가 있는 칸을 감쌉니다.\n"
            "(버튼마다 따로 그림을 저장하니, 4개 버튼 크기가 서로 달라도 괜찮습니다.)\n"
            "여러 버튼이 동시에 매진 아니게 되면, 번호가 빠른 쪽을 자동으로 클릭합니다.\n"
            "→ 원하는 열차·좌석을 앞 번호로 지정하세요.",
        )
        cfg["button_regions"].append(region)

    cfg["reserve_region"] = pick_region(
        "6. 예약 버튼",
        "버튼 중 하나가 매진 아니게 되어 클릭한 뒤, 이어서 누를 '예약' 버튼 영역을 감쌉니다.",
    )
    core.save_config(cfg)

    capture_templates(cfg)


if __name__ == "__main__":
    main()
