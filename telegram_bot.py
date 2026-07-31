#!/usr/bin/env python3
import json
import os
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from app import group_lines, items_to_csv, parse_items, parse_items_from_text, run_ocr

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
OFFSET_FILE = ROOT / ".telegram_offset"


class TelegramError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"

    def request(self, method, payload=None):
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}/{method}",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"Telegram HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise TelegramError(f"Telegram network error: {exc}") from exc

        if not result.get("ok"):
            raise TelegramError(result.get("description", "Telegram API error"))
        return result["result"]

    def get_updates(self, offset, timeout=30):
        payload = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self.request("getUpdates", payload)

    def send_message(self, chat_id, text, reply_to_message_id=None):
        payload = {
            "chat_id": chat_id,
            "text": text[:3900],
            "disable_web_page_preview": True,
        }
        if reply_to_message_id:
            payload["reply_parameters"] = {"message_id": reply_to_message_id}
        return self.request("sendMessage", payload)

    def get_file(self, file_id):
        return self.request("getFile", {"file_id": file_id})

    def download_file(self, file_path, destination):
        url = f"{self.file_base}/{file_path}"
        with urllib.request.urlopen(url, timeout=70) as response:
            destination.write_bytes(response.read())

    def send_document(self, chat_id, filename, content, caption=None):
        boundary = f"----yuan-cart-{uuid.uuid4().hex}"
        fields = {
            "chat_id": str(chat_id),
        }
        if caption:
            fields["caption"] = caption[:1024]

        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(b"Content-Type: text/csv; charset=utf-8\r\n\r\n")
        body.extend(content.encode("utf-8-sig"))
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        request = urllib.request.Request(
            f"{self.base}/sendDocument",
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=70) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise TelegramError(f"Telegram HTTP {exc.code}: {body_text}") from exc
        if not result.get("ok"):
            raise TelegramError(result.get("description", "Telegram API error"))
        return result["result"]


def load_offset():
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return None


def save_offset(offset):
    OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def allowed_users():
    raw = os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").strip()
    if not raw:
        return None
    return {int(part.strip()) for part in raw.split(",") if part.strip().isdigit()}


def user_is_allowed(message, allowlist):
    if allowlist is None:
        return True
    user = message.get("from") or {}
    return user.get("id") in allowlist


def format_items(items):
    if not items:
        return "没有解析到商品。可以直接粘贴 iPhone 实况文本，或者把购物车截图分段再发。"

    lines = [f"识别到 {len(items)} 个商品："]
    for index, item in enumerate(items, 1):
        name = item.get("name", "").strip()
        spec = item.get("spec", "").strip()
        quantity = item.get("quantity") or 1
        search = item.get("search") or " ".join(part for part in [name, spec] if part)
        lines.append(f"{index}. {search} x{quantity}")
    lines.append("")
    lines.append("请人工确认规格和数量，尤其是促销组合、称重商品和库存紧张商品。")
    return "\n".join(lines)


def send_items(api, chat_id, items, reply_to_message_id=None):
    api.send_message(chat_id, format_items(items), reply_to_message_id=reply_to_message_id)
    if items:
        csv_text = items_to_csv(items)
        api.send_document(chat_id, "yuan-cart-items.csv", csv_text, caption="商品清单 CSV")


def photo_file_id(message):
    photos = message.get("photo") or []
    if not photos:
        return None
    return max(photos, key=lambda photo: photo.get("file_size", 0)).get("file_id")


def document_file_id(message):
    document = message.get("document") or {}
    mime_type = document.get("mime_type", "")
    if mime_type.startswith("image/"):
        return document.get("file_id")
    return None


def parse_image(api, file_id):
    file_info = api.get_file(file_id)
    file_path = file_info["file_path"]
    suffix = Path(file_path).suffix or ".jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    image_path = UPLOAD_DIR / f"telegram-{uuid.uuid4().hex}{suffix}"
    api.download_file(file_path, image_path)
    lines = run_ocr(image_path)
    return parse_items(lines), "\n".join(line["text"] for line in group_lines(lines))


def handle_message(api, message, allowlist):
    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    if not user_is_allowed(message, allowlist):
        api.send_message(chat_id, "这个机器人当前只允许指定用户使用。", reply_to_message_id=message_id)
        return

    text = (message.get("text") or message.get("caption") or "").strip()

    if text in {"/start", "/help"}:
        api.send_message(
            chat_id,
            "把元初购物车的 iPhone 实况文本粘贴给我，我会返回商品清单和 CSV。\n\n"
            "也可以直接发截图，我会先尝试本机 OCR；如果失败，请改用实况文本复制。",
            reply_to_message_id=message_id,
        )
        return

    file_id = photo_file_id(message) or document_file_id(message)
    if file_id:
        api.send_message(chat_id, "收到截图，正在尝试识别...", reply_to_message_id=message_id)
        try:
            items, raw_text = parse_image(api, file_id)
            if not items and raw_text:
                api.send_message(chat_id, f"OCR 原文：\n{raw_text[:3500]}")
            send_items(api, chat_id, items, reply_to_message_id=message_id)
        except Exception as exc:
            api.send_message(
                chat_id,
                "图片 OCR 当前不可用。请在 iPhone 相册里用实况文本复制购物车文字，然后粘贴发给我。\n\n"
                f"错误：{str(exc)[:500]}",
                reply_to_message_id=message_id,
            )
        return

    if text:
        items = parse_items_from_text(text)
        send_items(api, chat_id, items, reply_to_message_id=message_id)
        return

    api.send_message(chat_id, "请发送购物车截图，或粘贴 iPhone 实况文本。", reply_to_message_id=message_id)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先设置 TELEGRAM_BOT_TOKEN。")

    api = TelegramAPI(token)
    allowlist = allowed_users()
    offset = load_offset()
    bot = api.request("getMe")
    print(f"机器人已启动：@{bot.get('username', 'unknown')}", flush=True)

    while True:
        try:
            updates = api.get_updates(offset=offset, timeout=int(os.environ.get("POLL_TIMEOUT", "30")))
            for update in updates:
                update_id = update["update_id"]
                offset = update_id + 1
                save_offset(offset)
                message = update.get("message")
                if message:
                    handle_message(api, message, allowlist)
        except KeyboardInterrupt:
            print("机器人已停止。", flush=True)
            return
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
