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


def pick_second_click(cfg):
    cfg["click_region2"] = pick_region(
        "4. 두 번째 클릭할 영역",
        "첫 번째 클릭 뒤에 이어서 누를 영역(예: 다음 화면의 '확인' 버튼 위치)을 감쌉니다.",
    )
    core.save_config(cfg)
    print("\n✅ 두 번째 클릭 영역 저장 완료.")


def main():
    cfg = core.load_config()

    if "--second-click" in sys.argv:
        print("[안내] 두 번째로 클릭할 화면 위치가 보이도록 크롬을 준비하세요.")
        print("       (검은 창이 그 위치를 가리지 않게 구석으로 옮겨 두세요.)")
        input("준비되면 Enter: ")
        pick_second_click(cfg)
        return

    if input("텔레그램 연결부터 할까요? (y/n): ").strip().lower() == "y":
        if not setup_telegram(cfg):
            return
        core.save_config(cfg)

    print("\n[준비] 크롬에서 감시할 열차가 '매진'으로 보이는 예매 화면을 열어 두세요.")
    print("[주의] 이 검은 창이 아래에 지정할 영역을 가리지 않도록 화면 구석에 옮겨 두세요.")
    input("준비되면 Enter: ")

    cfg["soldout_region"] = pick_region(
        "1. 매진 표시 칸",
        "감시할 열차 줄에서 '매진'(또는 예약하기 버튼) 글자가 있는 칸을 감쌉니다.",
    )
    cfg["anchor_region"] = pick_region(
        "2. 기준 칸",
        "같은 열차 줄에서 출발 시간처럼 항상 똑같이 보이는 글자 부분을 감쌉니다.\n"
        "(화면이 정상인지 확인하는 용도입니다.)",
    )
    cfg["click_region"] = pick_region(
        "3. 클릭할 영역",
        "예약 가능해졌을 때 클릭할 영역(예: 그 열차의 '예약하기' 버튼)을 감쌉니다.",
    )
    pick_second_click(cfg)

    print(f"\n{cfg['capture_delay']}초 뒤에 화면을 캡처합니다. 그동안 크롬 화면을 '매진' 상태로 두고,")
    print("검은 창이 지정한 영역을 가리지 않는지 확인하세요.")
    for s in range(cfg["capture_delay"], 0, -1):
        print(f"  {s}초 뒤 캡처...", end="\r", flush=True)
        time.sleep(1)
    print("  캡처합니다!            ")

    for path, key in ((core.SOLDOUT_IMG, "soldout_region"), (core.ANCHOR_IMG, "anchor_region")):
        shot = np.array(pyautogui.screenshot(region=tuple(cfg[key])))
        cv2.imwrite(str(path), cv2.cvtColor(shot, cv2.COLOR_RGB2BGR))
    core.save_config(cfg)

    print("\n✅ 저장 완료. 저장된 그림(ref_soldout.png, ref_anchor.png)을 열어서")
    print("   '매진' 칸과 '기준 칸'이 제대로 찍혔는지 확인해 보세요.")
    print("   다음 단계: python watcher.py --dry-run  (연습 실행)")


if __name__ == "__main__":
    main()
