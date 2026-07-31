#!/usr/bin/env python3
import cgi
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
BIN_DIR = ROOT / "bin"
BUILD_CACHE_DIR = ROOT / ".cache"
OCR_SWIFT = ROOT / "ocr.swift"
OCR_BIN = BIN_DIR / "yuan_cart_ocr"

IGNORE_WORDS = {
    "购物车", "全选", "结算", "删除", "编辑", "完成", "合计", "小计", "优惠",
    "去凑单", "推荐", "猜你喜欢", "到手价", "配送", "运费", "实付", "已选",
    "规格", "换购", "领券", "券", "活动", "失效", "清空", "会员", "登录",
    "即时送", "我常买", "外送", "自提", "库存紧张", "首页", "分类",
    "元初码", "个人中心",
}


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler, content, status=200, content_type="text/html; charset=utf-8"):
    body = content.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def ensure_ocr_binary():
    if OCR_BIN.exists() and OCR_BIN.stat().st_mtime >= OCR_SWIFT.stat().st_mtime:
        return

    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise RuntimeError("没有找到 swiftc，无法使用 macOS Vision OCR。")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_CACHE_DIR / "clang").mkdir(parents=True, exist_ok=True)
    (BUILD_CACHE_DIR / "swift").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = str(BUILD_CACHE_DIR / "clang")
    env["SWIFT_MODULE_CACHE_PATH"] = str(BUILD_CACHE_DIR / "swift")
    env["MODULE_CACHE_DIR"] = str(BUILD_CACHE_DIR / "clang")

    result = subprocess.run(
        [swiftc, str(OCR_SWIFT), "-o", str(OCR_BIN)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "OCR 编译失败。")


def run_ocr(image_path):
    ensure_ocr_binary()
    result = subprocess.run(
        [str(OCR_BIN), str(image_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "OCR 识别失败。")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OCR 返回格式异常: {exc}") from exc


def clean_line(text):
    text = text.strip()
    text = text.replace("￥", "¥").replace("Ｘ", "x").replace("×", "x")
    text = re.sub(r"\s+", " ", text)
    return text


def is_noise(text):
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if compact in IGNORE_WORDS:
        return True
    if any(word in compact for word in IGNORE_WORDS) and len(compact) <= 8:
        return True
    if "..." in text or "…" in text:
        return True
    if compact.endswith("私宅") or compact.endswith("住宅"):
        return True
    if re.fullmatch(r"[+\-xX×*]?\d{1,3}", compact):
        return True
    if re.fullmatch(r"(¥)?\d+(\.\d{1,2})?", compact):
        return True
    if re.fullmatch(r"(¥|￥)\s*\d+(\.\d{1,2})?", text):
        return True
    if re.search(r"(满|减|折|券|返|配送|运费|合计|小计)", compact) and len(compact) < 16:
        return True
    return False


def extract_quantity(text):
    compact = text.replace(" ", "")
    patterns = [
        r"(?:x|X|×|\*)\s*(\d{1,3})",
        r"数量[:：]?\s*(\d{1,3})",
        r"(\d{1,3})\s*(?:件|份|盒|袋|瓶|包)$",
        r"^(\d{1,2})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 99:
                return value
    return None


def looks_like_spec(text):
    compact = text.replace(" ", "")
    return bool(re.search(r"\d+(\.\d+)?\s*(g|kg|克|斤|ml|mL|L|升|枚|粒|个|盒|袋|瓶|包|份)", compact))


def looks_like_product(text):
    if is_noise(text):
        return False
    compact = re.sub(r"[^\w\u4e00-\u9fff]", "", text)
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    if chinese_count < 2:
        return False
    if len(compact) < 4:
        return False
    if re.search(r"(¥|￥|\d+\.\d{2})", text) and chinese_count < 5:
        return False
    return True


def group_lines(lines):
    cleaned = []
    for line in lines:
        text = clean_line(line.get("text", ""))
        if text:
            cleaned.append({
                "text": text,
                "confidence": line.get("confidence", 0),
                "x": line.get("x", 0),
                "y": line.get("y", 0),
                "width": line.get("width", 0),
                "height": line.get("height", 0),
            })
    return sorted(cleaned, key=lambda item: (-item["y"], item["x"]))


def parse_items(lines):
    ordered = group_lines(lines)
    items = []

    for index, line in enumerate(ordered):
        text = line["text"]
        if not looks_like_product(text):
            continue

        quantity = 1
        spec = ""
        search_window = ordered[index + 1:index + 7]

        for nearby in search_window:
            y_gap = abs(line["y"] - nearby["y"])
            if y_gap > 0.16:
                break
            found_qty = extract_quantity(nearby["text"])
            if found_qty:
                quantity = found_qty
                break

        for nearby in search_window[:3]:
            nearby_text = nearby["text"]
            if nearby_text == text or is_noise(nearby_text):
                continue
            if extract_quantity(nearby_text):
                continue
            if looks_like_spec(nearby_text):
                spec = nearby_text
                break

        confidence = float(line.get("confidence", 0))
        items.append({
            "name": text,
            "spec": spec,
            "quantity": quantity,
            "confidence": round(confidence, 3),
            "search": " ".join(part for part in [text, spec] if part),
        })

    deduped = []
    seen = set()
    for item in items:
        key = (item["name"], item["spec"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def parse_items_from_text(raw_text):
    fake_lines = []
    source_lines = [clean_line(line) for line in raw_text.splitlines()]
    source_lines = [line for line in source_lines if line]
    total = max(len(source_lines), 1)
    for index, text in enumerate(source_lines):
        fake_lines.append({
            "text": text,
            "confidence": 0,
            "x": 0,
            "y": 1 - (index / (total * 10)),
            "width": 1,
            "height": 0.02,
        })
    return parse_items(fake_lines)


def items_to_csv(items):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["name", "spec", "quantity", "search"])
    writer.writeheader()
    for item in items:
        writer.writerow({
            "name": item.get("name", ""),
            "spec": item.get("spec", ""),
            "quantity": item.get("quantity", 1),
            "search": item.get("search", ""),
        })
    return output.getvalue()


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>元初购物车截图助手</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #68757f;
      --line: #dce3e7;
      --green: #1f7a4d;
      --green-dark: #155c39;
      --blue: #235b8f;
      --red: #b42318;
      --amber: #8a5a05;
      --soft-green: #edf7f1;
      --soft-blue: #eef5fb;
      --shadow: 0 12px 32px rgba(20, 32, 38, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }

    button, input, textarea {
      font: inherit;
    }

    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }

    header {
      background: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 18px 28px;
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: center;
    }

    h1 {
      font-size: 20px;
      line-height: 1.2;
      margin: 0 0 4px;
      letter-spacing: 0;
    }

    .subtitle {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }

    .status {
      min-width: 180px;
      text-align: right;
      color: var(--muted);
      font-size: 13px;
    }

    main {
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }

    .panel-head {
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .panel-title {
      margin: 0;
      font-size: 15px;
      line-height: 1.2;
    }

    .upload {
      padding: 18px;
    }

    .dropzone {
      border: 1.5px dashed #aab7c0;
      background: #fbfcfc;
      border-radius: 8px;
      min-height: 220px;
      display: grid;
      place-items: center;
      text-align: center;
      padding: 22px;
      cursor: pointer;
      transition: border-color .16s, background .16s;
    }

    .dropzone.drag {
      border-color: var(--green);
      background: var(--soft-green);
    }

    .dropzone strong {
      display: block;
      margin-bottom: 8px;
      font-size: 16px;
    }

    .dropzone span {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }

    #fileInput {
      display: none;
    }

    .preview-wrap {
      margin-top: 16px;
      display: none;
    }

    .preview-wrap.visible {
      display: block;
    }

    .preview {
      width: 100%;
      max-height: 430px;
      object-fit: contain;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f9fafb;
    }

    .raw {
      margin: 16px 18px 18px;
      width: calc(100% - 36px);
      min-height: 150px;
      max-height: 260px;
      overflow: auto;
      white-space: pre-wrap;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      color: #26323a;
      background: #fbfcfd;
      font-size: 13px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      line-height: 1.45;
      resize: vertical;
    }

    .raw-panel {
      grid-column: 1 / -1;
    }

    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .btn {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      border-radius: 7px;
      padding: 8px 11px;
      cursor: pointer;
      min-height: 36px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }

    .btn:hover {
      border-color: #b5c2ca;
      background: #f7fafb;
    }

    .btn.primary {
      background: var(--green);
      border-color: var(--green);
      color: #ffffff;
    }

    .btn.primary:hover {
      background: var(--green-dark);
      border-color: var(--green-dark);
    }

    .btn.danger {
      color: var(--red);
    }

    .btn.small {
      min-height: 30px;
      padding: 5px 8px;
      font-size: 12px;
    }

    .btn:disabled {
      opacity: .55;
      cursor: not-allowed;
    }

    .table-wrap {
      overflow: auto;
    }

    table {
      width: 100%;
      min-width: 820px;
      border-collapse: collapse;
    }

    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: middle;
      text-align: left;
      font-size: 13px;
    }

    th {
      color: #44515a;
      background: #f8fafb;
      font-weight: 650;
      position: sticky;
      top: 0;
      z-index: 1;
    }

    td:first-child, th:first-child {
      padding-left: 18px;
    }

    td:last-child, th:last-child {
      padding-right: 18px;
    }

    .cell-input {
      width: 100%;
      border: 1px solid transparent;
      background: transparent;
      border-radius: 6px;
      padding: 7px 8px;
      color: var(--ink);
    }

    .cell-input:focus {
      outline: none;
      border-color: #8fb2cc;
      background: #ffffff;
      box-shadow: 0 0 0 3px rgba(35, 91, 143, .12);
    }

    .qty {
      width: 68px;
    }

    .confidence {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      white-space: nowrap;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--amber);
      flex: 0 0 auto;
    }

    .dot.high { background: var(--green); }
    .dot.low { background: var(--red); }

    .empty {
      padding: 44px 18px;
      text-align: center;
      color: var(--muted);
      line-height: 1.5;
    }

    .notice {
      margin: 0 18px 16px;
      padding: 11px 12px;
      border: 1px solid #c8d9e8;
      border-radius: 8px;
      color: #244b68;
      background: var(--soft-blue);
      font-size: 13px;
      line-height: 1.45;
    }

    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      background: #172026;
      color: #ffffff;
      padding: 10px 12px;
      border-radius: 8px;
      font-size: 13px;
      opacity: 0;
      transform: translateY(8px);
      pointer-events: none;
      transition: opacity .16s, transform .16s;
    }

    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }

    @media (max-width: 980px) {
      main {
        grid-template-columns: 1fr;
      }

      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .status {
        text-align: left;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div>
        <h1>元初购物车截图助手</h1>
        <p class="subtitle">整理购物车商品名、规格和数量；主流程支持粘贴 iPhone 实况文本，不登录、不下单。</p>
      </div>
      <div class="status" id="status">等待上传截图</div>
    </header>

    <main>
      <section class="panel">
        <div class="panel-head">
          <h2 class="panel-title">截图</h2>
          <button class="btn small" id="resetBtn" type="button">清空</button>
        </div>
        <div class="upload">
          <label class="dropzone" id="dropzone">
            <input id="fileInput" type="file" accept="image/*">
            <span>
              <strong>拖入截图尝试自动 OCR</strong>
              自动 OCR 是实验入口；如果失败，用 iPhone 实况文本复制后粘到下方原文区。
            </span>
          </label>
          <div class="preview-wrap" id="previewWrap">
            <img class="preview" id="preview" alt="上传的购物车截图预览">
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h2 class="panel-title">商品清单</h2>
          <div class="toolbar">
            <button class="btn" id="addRowBtn" type="button">新增一行</button>
            <button class="btn" id="copyBtn" type="button">复制搜索词</button>
            <button class="btn primary" id="csvBtn" type="button">导出 CSV</button>
          </div>
        </div>
        <p class="notice">结果要人工确认。商品规格、促销组合、缺货替代这些场景，后续接自动加购时也应该停下来让你确认。</p>
        <div class="table-wrap" id="tableWrap"></div>
      </section>

      <section class="panel raw-panel">
        <div class="panel-head">
          <h2 class="panel-title">OCR 原文</h2>
          <div class="toolbar">
            <button class="btn small" id="parseRawBtn" type="button">解析原文</button>
            <button class="btn small" id="copyRawBtn" type="button">复制原文</button>
          </div>
        </div>
        <textarea class="raw" id="rawText">上传截图后会显示 OCR 识别出的原始文本。自动 OCR 不可用时，可以用 iPhone/相册的实况文本复制购物车文字，粘到这里再点“解析原文”。</textarea>
      </section>
    </main>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    const fileInput = document.getElementById('fileInput');
    const dropzone = document.getElementById('dropzone');
    const preview = document.getElementById('preview');
    const previewWrap = document.getElementById('previewWrap');
    const statusEl = document.getElementById('status');
    const tableWrap = document.getElementById('tableWrap');
    const rawText = document.getElementById('rawText');
    const toast = document.getElementById('toast');
    const addRowBtn = document.getElementById('addRowBtn');
    const copyBtn = document.getElementById('copyBtn');
    const copyRawBtn = document.getElementById('copyRawBtn');
    const parseRawBtn = document.getElementById('parseRawBtn');
    const csvBtn = document.getElementById('csvBtn');
    const resetBtn = document.getElementById('resetBtn');

    let items = [];

    function showToast(message) {
      toast.textContent = message;
      toast.classList.add('show');
      window.setTimeout(() => toast.classList.remove('show'), 1800);
    }

    function setStatus(message) {
      statusEl.textContent = message;
    }

    function confidenceLabel(value) {
      const percent = Math.round((Number(value) || 0) * 100);
      return `${percent}%`;
    }

    function confidenceClass(value) {
      const number = Number(value) || 0;
      if (number >= 0.78) return 'high';
      if (number < 0.55) return 'low';
      return '';
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    }

    function renderTable() {
      if (!items.length) {
        tableWrap.innerHTML = '<div class="empty">还没有商品。上传截图后会自动生成，也可以手动新增。</div>';
        return;
      }

      tableWrap.innerHTML = `
        <table>
          <thead>
            <tr>
              <th style="width: 30%">商品名</th>
              <th style="width: 22%">规格</th>
              <th style="width: 8%">数量</th>
              <th style="width: 26%">搜索词</th>
              <th style="width: 8%">可信度</th>
              <th style="width: 6%">操作</th>
            </tr>
          </thead>
          <tbody>
            ${items.map((item, index) => `
              <tr>
                <td><input class="cell-input" data-field="name" data-index="${index}" value="${escapeHtml(item.name)}"></td>
                <td><input class="cell-input" data-field="spec" data-index="${index}" value="${escapeHtml(item.spec)}"></td>
                <td><input class="cell-input qty" type="number" min="1" data-field="quantity" data-index="${index}" value="${escapeHtml(item.quantity || 1)}"></td>
                <td><input class="cell-input" data-field="search" data-index="${index}" value="${escapeHtml(item.search || [item.name, item.spec].filter(Boolean).join(' '))}"></td>
                <td>
                  <span class="confidence"><span class="dot ${confidenceClass(item.confidence)}"></span>${confidenceLabel(item.confidence)}</span>
                </td>
                <td><button class="btn small danger" data-remove="${index}" type="button">删除</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    function syncDerivedSearch(index) {
      const item = items[index];
      if (!item) return;
      const generated = [item.name, item.spec].filter(Boolean).join(' ');
      if (!item.search || item.searchWasDerived) {
        item.search = generated;
        item.searchWasDerived = true;
      }
    }

    tableWrap.addEventListener('input', event => {
      const target = event.target;
      const index = Number(target.dataset.index);
      const field = target.dataset.field;
      if (!Number.isInteger(index) || !field || !items[index]) return;

      if (field === 'quantity') {
        items[index][field] = Math.max(1, Number(target.value) || 1);
      } else {
        const previousGenerated = [items[index].name, items[index].spec].filter(Boolean).join(' ');
        items[index][field] = target.value;
        if (field === 'search') {
          items[index].searchWasDerived = target.value === previousGenerated;
        }
        if (field === 'name' || field === 'spec') {
          syncDerivedSearch(index);
          renderTable();
        }
      }
    });

    tableWrap.addEventListener('click', event => {
      const removeIndex = event.target.dataset.remove;
      if (removeIndex === undefined) return;
      items.splice(Number(removeIndex), 1);
      renderTable();
      setStatus(`${items.length} 个商品待确认`);
    });

    function setPreview(file) {
      const url = URL.createObjectURL(file);
      preview.src = url;
      previewWrap.classList.add('visible');
    }

    async function uploadFile(file) {
      setPreview(file);
      setStatus('正在识别截图...');

      const formData = new FormData();
      formData.append('image', file);

      try {
        const response = await fetch('/api/ocr', {
          method: 'POST',
          body: formData
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || '识别失败');
        }
        items = data.items.map(item => ({ ...item, searchWasDerived: true }));
        rawText.value = data.raw_text || '没有识别到文本。';
        renderTable();
        setStatus(`${items.length} 个商品待确认`);
        showToast('识别完成');
      } catch (error) {
        setStatus('识别失败');
        showToast(error.message || '可以改用粘贴原文解析');
      }
    }

    async function parseRawText() {
      const text = rawText.value || rawText.textContent || '';
      if (!text.trim()) {
        showToast('先粘贴 OCR 原文');
        return;
      }
      setStatus('正在解析原文...');
      try {
        const response = await fetch('/api/parse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ raw_text: text })
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || '解析失败');
        }
        items = data.items.map(item => ({ ...item, searchWasDerived: true }));
        renderTable();
        setStatus(`${items.length} 个商品待确认`);
        showToast('原文解析完成');
      } catch (error) {
        setStatus('解析失败');
        showToast(error.message);
      }
    }

    fileInput.addEventListener('change', event => {
      const file = event.target.files[0];
      if (file) uploadFile(file);
    });

    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, event => {
        event.preventDefault();
        dropzone.classList.add('drag');
      });
    });

    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, event => {
        event.preventDefault();
        dropzone.classList.remove('drag');
      });
    });

    dropzone.addEventListener('drop', event => {
      const file = event.dataTransfer.files[0];
      if (file) uploadFile(file);
    });

    addRowBtn.addEventListener('click', () => {
      items.push({ name: '', spec: '', quantity: 1, search: '', confidence: 0, searchWasDerived: true });
      renderTable();
      setStatus(`${items.length} 个商品待确认`);
    });

    copyBtn.addEventListener('click', async () => {
      const text = items.map(item => {
        const qty = item.quantity || 1;
        const search = item.search || [item.name, item.spec].filter(Boolean).join(' ');
        return `${search} x${qty}`;
      }).filter(Boolean).join('\n');
      await navigator.clipboard.writeText(text);
      showToast('已复制搜索词');
    });

    copyRawBtn.addEventListener('click', async () => {
      await navigator.clipboard.writeText(rawText.value || rawText.textContent);
      showToast('已复制原文');
    });

    parseRawBtn.addEventListener('click', parseRawText);

    csvBtn.addEventListener('click', () => {
      const rows = [
        ['name', 'spec', 'quantity', 'search'],
        ...items.map(item => [item.name || '', item.spec || '', item.quantity || 1, item.search || ''])
      ];
      const csv = rows.map(row => row.map(cell => `"${String(cell).replaceAll('"', '""')}"`).join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'yuan-cart-items.csv';
      link.click();
      URL.revokeObjectURL(url);
    });

    resetBtn.addEventListener('click', () => {
      items = [];
      fileInput.value = '';
      preview.removeAttribute('src');
      previewWrap.classList.remove('visible');
      rawText.value = '上传截图后会显示 OCR 识别出的原始文本。自动 OCR 不可用时，可以用 iPhone/相册的实况文本复制购物车文字，粘到这里再点“解析原文”。';
      renderTable();
      setStatus('等待上传截图');
    });

    renderTable();
  </script>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            text_response(self, INDEX_HTML)
            return
        if parsed.path == "/health":
            json_response(self, {"ok": True})
            return
        text_response(self, "Not found", status=404, content_type="text/plain; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/parse":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body or "{}")
                raw_text = payload.get("raw_text", "")
                items = parse_items_from_text(raw_text)
                json_response(self, {"items": items})
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=500)
            return

        if parsed.path != "/api/ocr":
            json_response(self, {"error": "Not found"}, status=404)
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            json_response(self, {"error": "请上传图片文件。"}, status=400)
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                },
            )
            field = form["image"] if "image" in form else None
            if field is None or not getattr(field, "filename", ""):
                json_response(self, {"error": "没有收到图片。"}, status=400)
                return

            suffix = Path(field.filename).suffix.lower() or ".png"
            if suffix not in {".png", ".jpg", ".jpeg", ".heic", ".tiff", ".webp"}:
                suffix = ".png"

            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            image_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
            with image_path.open("wb") as output:
                shutil.copyfileobj(field.file, output)

            lines = run_ocr(image_path)
            items = parse_items(lines)
            raw_text = "\n".join(line["text"] for line in group_lines(lines))

            json_response(self, {
                "items": items,
                "raw_text": raw_text,
                "line_count": len(lines),
            })
        except subprocess.TimeoutExpired:
            json_response(self, {"error": "OCR 超时，请换一张更清晰或更小的截图。"}, status=500)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=500)


def main():
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), AppHandler)
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    print(f"元初购物车截图助手已启动: http://{display_host}:{port}", flush=True)
    if host == "0.0.0.0":
        print("局域网访问：请用 Mac 的 Wi-Fi IP 替换 127.0.0.1。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
