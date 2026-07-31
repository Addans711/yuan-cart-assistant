#!/usr/bin/env python3
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from app import parse_items_from_text

ROOT = Path(__file__).resolve().parent
QUEUE_DIR = ROOT / "queues"
BIN_DIR = ROOT / "bin"
CACHE_DIR = ROOT / ".cache"
MOUSE_SWIFT = ROOT / "mouse_position.swift"
MOUSE_BIN = BIN_DIR / "mouse_position"
CLICK_SWIFT = ROOT / "mouse_click.swift"
CLICK_BIN = BIN_DIR / "mouse_click"
MOVE_SWIFT = ROOT / "mouse_move.swift"
MOVE_BIN = BIN_DIR / "mouse_move"
KEY_SWIFT = ROOT / "key_press.swift"
KEY_BIN = BIN_DIR / "key_press"
TYPE_SWIFT = ROOT / "type_text.swift"
TYPE_BIN = BIN_DIR / "type_text"
BUTTON_SWIFT = ROOT / "button_state.swift"
BUTTON_BIN = BIN_DIR / "button_state"
FIND_ADD_SWIFT = ROOT / "find_add_button.swift"
FIND_ADD_BIN = BIN_DIR / "find_add_button"
DEFAULT_CONFIG = ROOT / "wechat_click_config.json"


def run(command, *, check=True, input_text=None):
    result = subprocess.run(
        command,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"命令失败：{' '.join(map(str, command))}\n{detail}")
    return result


def osascript(source):
    return run(["osascript", "-e", source])


def activate_wechat():
    errors = []
    for app_name in ("WeChat", "微信"):
        try:
            osascript(f'tell application "{app_name}" to activate')
            time.sleep(0.4)
            return app_name
        except Exception as exc:
            errors.append(str(exc))
    raise RuntimeError("没有找到 Mac 微信。请先打开微信，再重试。\n" + "\n".join(errors))


def copy_to_clipboard(text):
    run(["pbcopy"], input_text=text)


def type_text_direct(text):
    ensure_type_binary()
    run([str(TYPE_BIN), text])


def key_combo(key, modifier="command"):
    if modifier == "command" and key in {"a", "v"}:
        ensure_key_binary()
        run([str(KEY_BIN), f"cmd-{key}"])
        return
    osascript(f'''
tell application "System Events"
  keystroke "{key}" using {modifier} down
end tell
''')


def press_return():
    ensure_key_binary()
    run([str(KEY_BIN), "return"])


def click_at(point):
    x, y = point
    ensure_click_binary()
    run([str(CLICK_BIN), str(int(x)), str(int(y))])


def move_to(point):
    x, y = point
    ensure_move_binary()
    run([str(MOVE_BIN), str(int(x)), str(int(y))])


def ensure_swift_binary(source_path, output_path):
    if output_path.exists() and output_path.stat().st_mtime >= source_path.stat().st_mtime:
        return
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise RuntimeError("没有找到 swiftc，无法编译鼠标工具。")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "clang").mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "swift").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(CACHE_DIR / "clang")
    env["SWIFT_MODULE_CACHE_PATH"] = str(CACHE_DIR / "swift")
    env["MODULE_CACHE_DIR"] = str(CACHE_DIR / "clang")
    result = subprocess.run(
        [swiftc, str(source_path), "-o", str(output_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "鼠标工具编译失败。")


def ensure_mouse_binary():
    ensure_swift_binary(MOUSE_SWIFT, MOUSE_BIN)


def ensure_click_binary():
    ensure_swift_binary(CLICK_SWIFT, CLICK_BIN)


def ensure_move_binary():
    ensure_swift_binary(MOVE_SWIFT, MOVE_BIN)


def ensure_key_binary():
    ensure_swift_binary(KEY_SWIFT, KEY_BIN)


def ensure_type_binary():
    ensure_swift_binary(TYPE_SWIFT, TYPE_BIN)


def ensure_button_binary():
    ensure_swift_binary(BUTTON_SWIFT, BUTTON_BIN)


def ensure_find_add_binary():
    ensure_swift_binary(FIND_ADD_SWIFT, FIND_ADD_BIN)


def capture_screen(name):
    path = CACHE_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["screencapture", "-x", str(path)])
    return path


def button_state(point, radius=26):
    ensure_button_binary()
    screenshot_path = capture_screen("button_state_screen.png")
    result = run([
        str(BUTTON_BIN),
        str(int(point[0])),
        str(int(point[1])),
        str(screenshot_path),
        str(int(radius)),
    ])
    return json.loads(result.stdout)


def find_add_button():
    ensure_find_add_binary()
    screenshot_path = capture_screen("find_add_button_screen.png")
    result = run([str(FIND_ADD_BIN), str(screenshot_path)])
    payload = json.loads(result.stdout)
    if payload.get("found"):
        return int(payload["x"]), int(payload["y"]), payload
    return None, None, payload


def current_mouse_position():
    ensure_mouse_binary()
    result = run([str(MOUSE_BIN)])
    payload = json.loads(result.stdout)
    return int(payload["x"]), int(payload["y"])


def parse_point(value):
    if not value:
        return None
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("坐标格式应为 x,y，例如 420,180")
    return int(parts[0]), int(parts[1])


def point_to_text(point):
    return f"{int(point[0])},{int(point[1])}"


def load_config(path):
    config_path = Path(path)
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_config(path, config):
    config_path = Path(path)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def calibrate(config_path):
    activate_wechat()
    print("校准开始。请确保 Mac 微信里已经打开元初小程序。")
    print("")
    input("1. 把鼠标移动到左上角返回键中间，然后回到终端按回车：")
    back_click = current_mouse_position()
    print(f"已记录返回键坐标：{point_to_text(back_click)}")
    print("")
    input("2. 把鼠标移动到底部“首页”按钮中间，然后回到终端按回车：")
    home_click = current_mouse_position()
    print(f"已记录首页坐标：{point_to_text(home_click)}")
    print("")
    input("3. 点回首页后，把鼠标移动到元初小程序的搜索框中间，然后回到终端按回车：")
    search_click = current_mouse_position()
    print(f"已记录搜索框坐标：{point_to_text(search_click)}")
    print("")
    input("4. 搜索任意商品，让第一个商品的加购按钮显示出来；把鼠标移动到这个加购按钮中间，然后回到终端按回车：")
    add_click = current_mouse_position()
    print(f"已记录加购按钮坐标：{point_to_text(add_click)}")
    print("")
    config = {
        "back_click": list(back_click),
        "home_click": list(home_click),
        "search_click": list(search_click),
        "add_click": list(add_click),
        "search_wait": 1.2,
        "after_add_wait": 0.6,
    }
    save_config(config_path, config)
    print(f"校准完成，配置已保存到 {config_path}")
    print("下一步可以先用单商品全自动测试：")
    print('python3 mac_wechat_add_to_cart.py --item "东寮豆干200g（两个）" --full-auto')
    return 0


def test_add_click(args):
    config = load_config(args.config)
    add_click = args.add_click or tuple(config.get("add_click") or [])
    if not add_click:
        raise RuntimeError("没有加购按钮坐标。请先运行：python3 mac_wechat_add_to_cart.py --calibrate")
    if not args.skip_activate:
        try:
            activate_wechat()
        except Exception as exc:
            print("警告：无法激活微信，将继续使用当前屏幕坐标测试。")
            print(str(exc).splitlines()[0])
    move_to(add_click)
    print(f"鼠标已移动到加购坐标 {point_to_text(add_click)}。")
    print("请确认鼠标是否停在当前商品的加购按钮上。")
    if not wait_user("确认后按回车点击；输入 n 不点击：", args.yes):
        print("已取消点击。")
        return 1
    click_at(add_click)
    print("已点击一次加购坐标。请检查购物车数量是否变化。")
    return 0


def load_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        items = []
        for row in reader:
            name = (row.get("name") or "").strip()
            spec = (row.get("spec") or "").strip()
            search = (row.get("search") or " ".join(part for part in [name, spec] if part)).strip()
            if not search:
                continue
            try:
                quantity = int(row.get("quantity") or "1")
            except ValueError:
                quantity = 1
            items.append({
                "name": name or search,
                "spec": spec,
                "quantity": max(1, quantity),
                "search": search,
            })
    return items


def load_text(path):
    text = Path(path).read_text(encoding="utf-8")
    return parse_items_from_text(text)


def save_queue(items, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["name", "spec", "quantity", "search"])
        writer.writeheader()
        for item in items:
            writer.writerow({
                "name": item.get("name", ""),
                "spec": item.get("spec", ""),
                "quantity": item.get("quantity", 1),
                "search": item.get("search", ""),
            })


def append_unavailable(item, path, reason="没货或未加购"):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exists = output_path.exists()
    with output_path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["name", "spec", "quantity", "search", "reason"])
        if not exists:
            writer.writeheader()
        writer.writerow({
            "name": item.get("name", ""),
            "spec": item.get("spec", ""),
            "quantity": item.get("quantity", 1),
            "search": item.get("search", ""),
            "reason": reason,
        })


def wait_user(prompt, assume_yes=False):
    if assume_yes:
        print(prompt)
        return True
    answer = input(prompt).strip().lower()
    return answer not in {"n", "no", "否", "不"}


def apply_full_auto_defaults(args):
    config = load_config(args.config)
    if not args.back_click and config.get("back_click"):
        args.back_click = tuple(config["back_click"])
    if not args.home_click and config.get("home_click"):
        args.home_click = tuple(config["home_click"])
    if not args.search_click and config.get("search_click"):
        args.search_click = tuple(config["search_click"])
    if not args.add_click and config.get("add_click"):
        args.add_click = tuple(config["add_click"])
    if args.search_wait is None:
        args.search_wait = float(config.get("search_wait", 1.2))
    if args.after_add_wait is None:
        args.after_add_wait = float(config.get("after_add_wait", 0.6))

    if args.full_auto:
        args.auto_paste = True
        args.yes = True
        if args.detect_stock and args.back_on_skip == 0:
            args.back_on_skip = 2
        if args.back_after_add == 0:
            args.back_after_add = 2
        missing = []
        if not args.home_click:
            missing.append("首页坐标")
        if not args.search_click:
            missing.append("搜索框坐标")
        if not args.add_click:
            missing.append("加购按钮坐标")
        if args.detect_stock and args.back_on_skip > 0 and not args.back_click:
            missing.append("返回键坐标")
        if args.back_after_add > 0 and not args.back_click:
            missing.append("返回键坐标")
        if missing:
            raise RuntimeError(
                "缺少" + "、".join(missing) + "。请先运行：\n"
                "python3 mac_wechat_add_to_cart.py --calibrate"
            )


def run_guided(items, args):
    if not items:
        print("没有可执行的商品。")
        return 1

    if args.skip_activate:
        print("已跳过激活微信；将直接使用当前屏幕坐标。")
    else:
        app_name = activate_wechat()
        print(f"已激活 {app_name}。")
    print("请先在 Mac 微信里打开元初小程序，并进入可搜索商品的页面。")
    if args.full_auto:
        print("全自动模式：脚本会自动点击搜索框、粘贴搜索词、回车搜索、点击加购。")
        print("请不要离开元初小程序窗口；支付必须人工操作。")
    else:
        print("默认流程不会自动点击加购，只会复制搜索词；你确认后再手动加购。")
    print("")

    for index, item in enumerate(items, 1):
        search = item.get("search") or item.get("name") or ""
        quantity = int(item.get("quantity") or 1)
        if not search:
            continue

        print(f"[{index}/{len(items)}] {search} x{quantity}")
        if not wait_user("按回车复制这个搜索词并激活微信；输入 n 跳过：", args.yes):
            print("已跳过。")
            continue

        if not args.direct_type:
            try:
                copy_to_clipboard(search)
            except Exception as exc:
                print("警告：剪贴板不可用，改用直接输入文字。")
                print(str(exc).splitlines()[0])
                args.direct_type = True
        if not args.skip_activate:
            activate_wechat()

        if args.home_click:
            click_at(args.home_click)
            time.sleep(args.pause)

        if args.search_click:
            click_at(args.search_click)
            time.sleep(args.pause)

        if args.auto_paste:
            key_combo("a")
            time.sleep(0.1)
            if args.direct_type:
                type_text_direct(search)
            else:
                key_combo("v")
            time.sleep(0.1)
            press_return()
            time.sleep(args.search_wait)
            print("已粘贴并回车搜索。")
        else:
            print("已复制到剪贴板。请在元初小程序搜索框里粘贴并搜索。")

        if args.add_click:
            click_target = args.add_click
            found_by_auto_find = False
            if args.auto_find_add:
                found_x, found_y, find_payload = find_add_button()
                if found_x is None:
                    append_unavailable(item, args.unavailable_csv, reason="未找到绿色加购按钮")
                    print(f"未找到绿色加购按钮，已记录未加购：{search}")
                    if args.back_click and args.back_on_skip > 0:
                        for _ in range(args.back_on_skip):
                            click_at(args.back_click)
                            time.sleep(args.pause)
                        print(f"已点击返回键 {args.back_on_skip} 次。")
                    print("")
                    continue
                click_target = (found_x, found_y)
                found_by_auto_find = True
                print(
                    f"自动找到加购按钮：{point_to_text(click_target)} "
                    f"area={find_payload.get('area')} density={find_payload.get('density')}"
                )
            detected_addable = True
            if args.detect_stock and not found_by_auto_find:
                state = button_state(click_target, args.detect_radius)
                detected_addable = bool(state.get("addable"))
                print(
                    "按钮检测："
                    f"green={state.get('green_ratio')} "
                    f"white={state.get('white_ratio')} "
                    f"addable={detected_addable}"
                )
                if not detected_addable:
                    append_unavailable(item, args.unavailable_csv, reason="检测到到货通知/补货中/非加购按钮")
                    print(f"已跳过并记录缺货：{search}")
                    if args.back_click and args.back_on_skip > 0:
                        for _ in range(args.back_on_skip):
                            click_at(args.back_click)
                            time.sleep(args.pause)
                        print(f"已点击返回键 {args.back_on_skip} 次。")
                    print("")
                    continue
            if args.confirm_each or not args.full_auto:
                move_to(click_target)
                print(f"鼠标已移动到加购坐标 {point_to_text(click_target)}。")
                print("如果看到“到货通知/补货中/没货”，输入 n 记录缺货并跳过。")
            should_click = wait_user("看到绿色加购按钮就按回车；没货/不确定输入 n：", args.yes and not args.confirm_each)
            if should_click:
                for count in range(quantity):
                    click_at(click_target)
                    time.sleep(args.after_add_wait)
                print(f"已点击加购坐标 {quantity} 次。")
                if args.back_click and args.back_after_add > 0:
                    for _ in range(args.back_after_add):
                        click_at(args.back_click)
                        time.sleep(args.pause)
                    print(f"已点击返回键 {args.back_after_add} 次。")
            else:
                append_unavailable(item, args.unavailable_csv)
                print(f"已记录未加购：{search}")
                if args.back_click and args.back_on_skip > 0:
                    for _ in range(args.back_on_skip):
                        click_at(args.back_click)
                        time.sleep(args.pause)
                    print(f"已点击返回键 {args.back_on_skip} 次。")
        else:
            print("请手动选择匹配商品并加购。")

        print("")

    print("队列执行完毕。请人工检查元初购物车，不要自动支付。")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Mac 微信元初小程序加购助手。默认半自动；校准坐标后可全自动搜索并点击加购。",
    )
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument("--csv", help="网页或 Telegram Bot 导出的商品 CSV。")
    input_group.add_argument("--text", help="包含购物车实况文本的 txt 文件。")
    input_group.add_argument("--item", help="单个搜索词，用于测试一件商品。")
    parser.add_argument("--calibrate", action="store_true", help="校准搜索框和加购按钮坐标，并保存到配置文件。")
    parser.add_argument("--test-add-click", action="store_true", help="只测试已保存的加购按钮坐标：移动鼠标，确认后点击一次。")
    parser.add_argument("--full-auto", action="store_true", help="全自动模式：读取配置坐标，自动搜索并点击加购。不会自动支付。")
    parser.add_argument("--confirm-each", action="store_true", help="每个商品搜索后停下确认；输入 n 会记录到缺货清单并跳过。")
    parser.add_argument("--detect-stock", action="store_true", help="点击前检测加购坐标附近是否为绿色实心加购按钮；否则记录缺货并跳过。")
    parser.add_argument("--detect-radius", type=int, default=26, help="按钮检测半径。")
    parser.add_argument("--auto-find-add", action="store_true", help="从屏幕截图自动寻找绿色实心加购按钮，不使用固定加购坐标。")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="坐标配置文件路径。")
    parser.add_argument("--skip-activate", action="store_true", help="不尝试激活微信，直接使用当前屏幕坐标。")
    parser.add_argument("--auto-paste", action="store_true", help="自动 Cmd+A、Cmd+V、回车搜索。需要你先让搜索框获得焦点，或配合 --search-click。")
    parser.add_argument("--direct-type", action="store_true", help="不使用剪贴板，直接向搜索框输入文字。")
    parser.add_argument("--back-click", type=parse_point, help="左上角返回键屏幕坐标 x,y。")
    parser.add_argument("--back-on-skip", type=int, default=0, help="跳过没货商品后点击返回键的次数。")
    parser.add_argument("--back-after-add", type=int, default=0, help="成功加购后点击返回键的次数。全自动默认 2 次。")
    parser.add_argument("--home-click", type=parse_point, help="底部首页按钮屏幕坐标 x,y。启用后每个商品先回首页。")
    parser.add_argument("--search-click", type=parse_point, help="搜索框屏幕坐标 x,y。启用后会先点击这里。")
    parser.add_argument("--add-click", type=parse_point, help="加购按钮屏幕坐标 x,y。启用后会在确认后点击这里。")
    parser.add_argument("--pause", type=float, default=0.6, help="自动动作之间的等待秒数。")
    parser.add_argument("--search-wait", type=float, default=None, help="回车搜索后等待结果加载的秒数。")
    parser.add_argument("--after-add-wait", type=float, default=None, help="每次点击加购后的等待秒数。")
    parser.add_argument("--yes", action="store_true", help="跳过每件商品的回车确认。只建议在坐标验证稳定后使用。")
    parser.add_argument("--save-queue", default=str(QUEUE_DIR / "latest_items.csv"), help="保存本次待加购队列 CSV。")
    parser.add_argument("--unavailable-csv", default=str(QUEUE_DIR / "unavailable_items.csv"), help="记录没货/未加购商品的 CSV。")
    args = parser.parse_args()

    if args.calibrate:
        return calibrate(args.config)

    if args.test_add_click:
        return test_add_click(args)

    if not (args.csv or args.text or args.item):
        parser.error("请提供 --csv、--text、--item，或使用 --calibrate。")

    apply_full_auto_defaults(args)

    if args.csv:
        items = load_csv(args.csv)
    elif args.text:
        items = load_text(args.text)
    else:
        items = [{"name": args.item, "spec": "", "quantity": 1, "search": args.item}]

    save_queue(items, args.save_queue)
    print(f"已加载 {len(items)} 个商品，队列已保存到 {args.save_queue}")
    return run_guided(items, args)


if __name__ == "__main__":
    raise SystemExit(main())
