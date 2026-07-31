# 元初购物车截图助手

本地 MVP：把元初 App 购物车截图里的文字整理成可编辑商品清单。

当前可用主流程是：在 iPhone 相册或截图预览里用“实况文本”复制购物车文字，粘贴到页面的“OCR 原文”，点击“解析原文”。页面里也保留了 macOS Vision 自动 OCR 入口，但在当前 Codex 沙盒中 Vision 文本识别不可用，所以先按实验功能处理。

## 运行

```bash
cd yuan_cart_assistant
python3 app.py
```

打开：

```text
http://127.0.0.1:8765
```

## 在 iPhone 打开

Mac 和 iPhone 需要连同一个 Wi-Fi。

1. 在 Mac 上查 Wi-Fi IP：

```bash
ipconfig getifaddr en0
```

2. 用局域网模式启动：

```bash
cd yuan_cart_assistant
HOST=0.0.0.0 PORT=8767 python3 app.py
```

3. 在 iPhone Safari 打开：

```text
http://你的Mac-IP:8767
```

例如 Mac IP 是 `192.168.1.23`，就打开：

```text
http://192.168.1.23:8767
```

如果打不开，检查 macOS 防火墙是否拦截 Python 接收入站连接，或确认两台设备在同一个 Wi-Fi。

## 当前能力

- 上传 PNG/JPG/HEIC 等图片。
- 粘贴实况文本后自动提取候选商品名、规格、数量。
- 保留本机 OCR 接口，不把截图传到外部服务。
- 自动提取候选商品名、规格、数量。
- 可手动编辑、增删行。
- 可复制搜索词，或导出 CSV。

## 适合的截图

- 元初 App 购物车页面，商品行尽量完整。
- 如果购物车很长，建议分多张截图上传后合并清单。
- 字体太小、图片模糊、折叠规格、促销文字过多时，需要人工修正。

## iPhone 使用方法

1. 打开元初 App 购物车并截图。
2. 在 iPhone 相册中打开截图，长按文字或点“实况文本”按钮。
3. 复制购物车文字，发到 Mac 或直接粘到网页的“OCR 原文”里。
4. 点“解析原文”，检查商品名、规格、数量。
5. 复制搜索词或导出 CSV。

## 后续可接

- 用识别清单驱动 iPhone 自动化搜索和加购。
- 增加元初商品名纠错词典。
- 按历史确认结果训练更稳定的匹配规则。

## Mac 微信小程序半自动加购

如果你在 Mac 微信里能打开元初小程序，可以用 `mac_wechat_add_to_cart.py` 读取商品清单并辅助搜索。默认模式只会复制搜索词、激活微信，不会自动点击加购。

### 单商品测试

1. 在 Mac 微信里打开元初小程序。
2. 进入可以搜索商品的页面。
3. 运行：

```bash
cd yuan_cart_assistant
python3 mac_wechat_add_to_cart.py --item "美人腿茭白450g±20g"
```

脚本会把搜索词复制到剪贴板并激活微信。你手动粘贴、搜索、确认商品并加购。

### 用 CSV 批量辅助

先从网页或 Telegram Bot 导出 `yuan-cart-items.csv`，再运行：

```bash
cd yuan_cart_assistant
python3 mac_wechat_add_to_cart.py --csv /path/to/yuan-cart-items.csv
```

### 自动粘贴搜索

如果你已经让元初小程序的搜索框获得焦点，可以让脚本自动粘贴并回车：

```bash
python3 mac_wechat_add_to_cart.py --csv /path/to/yuan-cart-items.csv --auto-paste
```

### 坐标点击模式

确认搜索框和加购按钮位置稳定后，可以指定屏幕坐标：

```bash
python3 mac_wechat_add_to_cart.py \
  --csv /path/to/yuan-cart-items.csv \
  --search-click 420,180 \
  --add-click 780,520 \
  --auto-paste
```

坐标模式可能需要在 macOS 系统设置里允许终端或 Python 使用“辅助功能”。先用单个商品测试，不要直接跑整车商品；支付必须人工操作。

### 全自动模式

全自动前先校准一次坐标：

```bash
cd yuan_cart_assistant
python3 mac_wechat_add_to_cart.py --calibrate
```

校准时按提示操作：

1. Mac 微信里打开元初小程序。
2. 把鼠标放到左上角返回键中间，回到终端按回车。
3. 把鼠标放到底部“首页”按钮中间，回到终端按回车。
4. 点回首页后，把鼠标放到搜索框中间，回到终端按回车。
5. 搜索任意商品，让第一个商品的加购按钮显示出来。
6. 把鼠标放到搜索结果里第一个商品的加购按钮中间，回到终端按回车。

然后先用一个商品测试全自动：

```bash
python3 mac_wechat_add_to_cart.py --item "东寮豆干200g（两个）" --full-auto
```

确认能自动搜索并加购后，再跑 CSV。推荐使用自动识别绿色加号模式：

```bash
python3 mac_wechat_add_to_cart.py \
  --csv /path/to/yuan-cart-items.csv \
  --full-auto \
  --auto-find-add \
  --detect-stock \
  --search-wait 2 \
  --unavailable-csv queues/unavailable_items.csv
```

如果搜索结果加载慢，可以加长等待：

```bash
python3 mac_wechat_add_to_cart.py --csv /path/to/yuan-cart-items.csv --full-auto --search-wait 2
```

全自动只负责加入购物车；支付、地址、验证码、替代商品必须人工确认。

全自动模式下：

- 有绿色加号：点击加购，然后自动点两次左上角返回。
- 没有绿色加号，或显示“到货通知/补货中”：记录到缺货 CSV，然后自动点两次左上角返回。

如需手动指定返回次数，可以加参数：

```bash
python3 mac_wechat_add_to_cart.py \
  --csv /path/to/yuan-cart-items.csv \
  --full-auto \
  --auto-find-add \
  --detect-stock \
  --back-on-skip 2 \
  --back-after-add 2
```

## Telegram Bot 部署

这个项目也带了一个 Telegram 机器人版本。它使用 Telegram Bot API 的 long polling 模式，不需要公网域名或 webhook。

### 1. 创建机器人

1. 在 Telegram 搜索 `@BotFather`。
2. 发送 `/newbot`。
3. 按提示设置机器人名称和 username。
4. 复制 BotFather 给你的 token。

### 2. 本机运行

```bash
cd yuan_cart_assistant
export TELEGRAM_BOT_TOKEN="你的BotToken"
python3 telegram_bot.py
```

运行后，在 Telegram 里给机器人发送：

- `/start` 查看说明。
- 直接粘贴 iPhone 实况文本，机器人会返回商品清单和 CSV。
- 发送截图，机器人会尝试本机 OCR；如果 OCR 不可用，会提示改用实况文本。

### 3. 限制使用者

如果不想让别人用你的机器人，可以限制 Telegram 用户 ID：

```bash
export ALLOWED_TELEGRAM_USER_IDS="123456789,987654321"
python3 telegram_bot.py
```

用户 ID 可以通过 Telegram 的 `@userinfobot` 查询。

### 4. 部署到服务器

在一台长期在线的 Mac 或云服务器上运行同样命令即可。云服务器如果是 Linux，截图 OCR 需要另接 OCR 服务；粘贴实况文本解析不受影响。

官方 Bot API 参考：

- `getUpdates`：用于 long polling 接收消息。
- `getFile`：用于下载用户发来的图片。
- `sendMessage` / `sendDocument`：用于返回清单和 CSV。

## GitHub 注意事项

以下内容属于本机运行数据，不应该上传到仓库，已经通过 `.gitignore` 排除：

- `.cache/`
- `bin/`
- `uploads/`
- `queues/*.csv`
- `.telegram_offset`
- `.env`
- `wechat_click_config.json`

如果要保留坐标配置格式，可以参考 `wechat_click_config.example.json`，但真实坐标建议只留在本机。
