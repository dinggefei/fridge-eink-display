# 后端服务

Python FastAPI 服务端。当前已打通 PostgreSQL 数据模型与迁移、微信登录、
家庭空间库存 API、动态四色设备帧、ETag 和 HMAC-SHA256 设备鉴权。本地 JSON
库存接口暂时保留，用于数据库尚未启动时兼容已跑通的硬件链路。

## 当前内容

- `app/domain/inventory.py`：食材状态计算、排序和先到期先扣减。
- `app/services/inventory_store.py`：本地 JSON 持久化开发库存。
- `app/api/inventory.py`：库存增删改查和家庭名称 API。
- `app/api/auth.py`：微信登录、本地开发登录和自定义登录态。
- `app/api/household_inventory.py`：带用户与家庭权限校验的正式库存 API。
- `app/api/recognition.py`：快速记一笔、订单图片任务和确认入库 API。
- `app/api/display_album.py`：家庭墨水屏相册、预览确认、排序和轮播设置 API。
- `app/api/display_market.py`：家庭行情自选、排序、刷新周期和缓存报价 API。
- `app/api/display_timetable.py`：家庭共享课表、节次设置、竖横屏方向和真实预览 API。
- `app/api/display_settings.py`：食材、黄历、七日天气、课表、行情、相册六种互斥
  显示模式 API。
- `app/services/almanac.py`：使用固定版本 `lunar-python 1.4.8` 计算农历、干支、
  生肖、节气、宜忌和冲煞。
- `app/services/weather.py`：黄历天气城市搜索、和风天气 JWT、3 小时缓存与失败回退。
- `app/services/recognition.py`：可替换的模拟/腾讯混元识别适配层。
- `app/services/display_photos.py`：3:5 居中裁切、480×800 缩放、四色抖动和轮播选择。
- `app/services/display_photo_storage.py`：本地开发存储和腾讯云私有 COS 存储适配层。
- `app/services/market_data.py`：CoinGecko、Twelve Data 与本地模拟行情适配层。
- `app/services/recognition_tasks.py`：临时图片、识别任务和事务性库存操作。
- `app/worker.py`：生产环境 PostgreSQL 识别任务 worker。
- `app/db/models.py`：MVP 核心数据库模型。
- `app/services/display_renderer.py`：480×800 竖屏排版，并转换为 800×480
  GDEM075F53 原生四色帧。
- `app/services/device_auth.py`：时间戳、nonce 和 HMAC-SHA256 设备鉴权。
- `app/api/devices.py`：BLE 配网会话、绑定、解绑和小程序码 API。
- `app/api/device_ota.py`：私有固件下载和安装结果回报 API。
- `app/services/device_ota.py`：硬件/版本筛选、白名单金丝雀和确定性灰度。
- `app/services/device_provisioning.py`：挑战绑定的 AES-GCM 配网密文。
- `app/services/mini_program_code.py`：微信小程序码生成与缓存。
- `migrations/versions/0001_initial.py`：首个数据库迁移。
- `app/main.py`：FastAPI 应用入口和健康检查。
- `tests/test_inventory.py`：PRD 业务边界测试。

## 安装与运行

首次安装依赖：

```bash
cd backend
uv sync
```

先按 `../infra/README.md` 启动 PostgreSQL，再执行：

```bash
uv run alembic upgrade head
```

本机 `.env` 与 ESP32 `device_secrets.h` 已生成匹配的设备密钥，不要使用
`.env.example` 覆盖它。启动：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

预期响应：

```json
{"service":"refrigerator-food-management","status":"ok"}
```

`--host 0.0.0.0` 允许同一局域网中的 ESP32-S3 访问服务。首次启动时如果
macOS 询问是否允许传入网络连接，请选择“允许”。开发阶段只应在可信任的家庭
局域网中使用该配置。

## 库存 API

打开交互式接口文档：

```text
http://127.0.0.1:8000/docs
```

正式库存接口必须携带用户登录令牌，并且按家庭空间隔离：

```text
GET    /v1/households/{household_id}/inventory
POST   /v1/households/{household_id}/inventory
PUT    /v1/households/{household_id}/inventory/{item_id}
DELETE /v1/households/{household_id}/inventory/{item_id}
```

微信小程序先调用 `wx.login()` 取得一次性 `code`，再调用：

```text
POST /v1/auth/wechat
{"code": "wx.login 返回的一次性 code"}
```

开发阶段可以调用 `POST /v1/auth/dev-login`。该接口受
`ALLOW_DEV_LOGIN=true` 控制，生产环境会强制禁止。AppSecret 只能配置在后端
`.env`，不得写入小程序、Git 或聊天消息。

迁移完成并完成一次开发登录后，把 `.env` 中
`DATABASE_INVENTORY_ENABLED` 改为 `true`，墨水屏设备接口就会读取绑定家庭的
PostgreSQL 库存。原开发库存会在首次开发登录时自动导入。

生成静态屏幕预览：

```bash
uv run python -m tools.render_display_preview
```

生成当前持久化库存对应的设备画面：

```bash
uv run python -m tools.render_current_inventory
```

硬件联调画面：

```bash
curl --output /tmp/rfm-frame.bin \
  http://127.0.0.1:8000/v1/bringup/frame
wc -c /tmp/rfm-frame.bin
```

文件必须为 `96000` 字节。`/v1/bringup/frame` 是不带设备鉴权的临时联调
接口，只能用于可信任的开发局域网。

正式设备接口：

```text
GET /v1/devices/{device_code}/frame
```

本地 `.env` 中的 `DEVICE_CODE` 和 `DEVICE_SECRET` 必须与 ESP32 本地
`device_secrets.h` 一致。请求签名规则见
`../shared/protocol/device-frame-v1.md`。两个本地配置文件均不得提交或分享。

## ESP32 签名 OTA

OTA 使用现有画面请求作为控制通道：支持 OTA 的设备在每次五分钟唤醒请求中上报
固件版本、构建号和硬件型号，服务端在 HTTP 200 或 304 响应头中返回可用版本。
二进制只通过设备 HMAC 鉴权接口下载，不放在静态目录或公共对象存储中。

服务端只接收 Arduino-ESP32 `bin_signing.py` 生成的 ECDSA P-256 + SHA-256
签名包。导入时同时验证签名、大小和 SHA-256；默认状态始终为 `draft`，不会自动
发给设备。以下命令必须在已经运行数据库迁移的环境执行：

```bash
uv run python -m tools.firmware_release import \
  --binary /安全路径/frame_download_display-signed.bin \
  --public-key /安全路径/ota_public_key.pem \
  --version 1.0.1 \
  --build 10001 \
  --notes "首个 OTA 验证版本"
```

先只允许一台测试设备升级：

```bash
uv run python -m tools.firmware_release status RELEASE_ID canary \
  --device rfm-test-device
```

确认设备升级、重启、回报 `installed` 且水墨屏仍能刷新后，才逐步扩大灰度：

```bash
uv run python -m tools.firmware_release status RELEASE_ID published \
  --rollout 10
uv run python -m tools.firmware_release status RELEASE_ID published \
  --rollout 100
```

发现异常立即暂停；已经成功安装的设备不会降级，尚未升级的设备不再收到该版本：

```bash
uv run python -m tools.firmware_release status RELEASE_ID paused
```

完整签名、首次 USB 迁移、验收和回滚规则见
`../shared/protocol/device-ota-v1.md`。

BLE 配网和绑定协议见 `../shared/protocol/device-provisioning-v1.md`。注册新
设备时，工具会生成 256 位密钥、写入数据库加密字段，并把固件头文件以 `0600`
权限写到指定的新路径；密钥不会输出到终端：

```bash
uv run python -m tools.manage_device register \
  --device-code RFM-S3-000002 \
  --header-output /安全路径/device_secrets.h
```

准备出售的新设备优先使用批次出厂工具。它会同时完成唯一编号、数据库注册、
微信小程序码、固件头文件、可打印标签、无密钥清单和强制出厂检查：

```bash
uv run python -m tools.factory_device create-batch \
  --count 5 \
  --code-prefix rfm-26 \
  --output-dir /安全路径/rfm-factory-batch-001
```

完整制造、烧录、测试、清除 NVS 和发货检查流程见
`../docs/FACTORY_PROVISIONING.md`。

轮换会立即让旧固件离线，只能在准备好重新刷写设备时执行：

```bash
uv run python -m tools.manage_device rotate \
  --device-code RFM-S3-000002 \
  --header-output /安全路径/device_secrets.rotated.h \
  --confirm-device-offline
```

## 快速记一笔与订单识别

本地默认使用确定性的模拟识别器，不消耗模型额度：

```dotenv
RECOGNITION_PROVIDER=mock
RECOGNITION_EXECUTION_MODE=inline
```

生产环境必须使用真实模型并由独立 worker 执行：

```dotenv
RECOGNITION_PROVIDER=hunyuan
RECOGNITION_EXECUTION_MODE=worker
RECOGNITION_IMAGE_CONCURRENCY=2
HUNYUAN_API_KEY=在腾讯混元控制台创建的 OpenAI 兼容 API Key
```

主要接口：

```text
POST /v1/households/{id}/quick-entry/parse
POST /v1/households/{id}/quick-entry/{task_id}/confirm
POST /v1/households/{id}/imports
POST /v1/households/{id}/imports/{task_id}/images
POST /v1/households/{id}/imports/{task_id}/start
GET  /v1/households/{id}/imports/{task_id}
POST /v1/households/{id}/imports/{task_id}/confirm
POST /v1/households/{id}/imports/{task_id}/cancel
```

解析和识别只生成草稿，不会修改库存。只有 confirm 接口会在数据库事务中写入，
同时锁定任务和家庭库存版本；重复确认不会重复入库。图片上传后会去除 EXIF、
统一转为 JPEG，识别成功后立即删除，异常文件最迟 24 小时清理。

## 墨水屏相册

家庭管理员和普通成员拥有相同的相册管理权限。每个家庭最多保存 6 张照片，支持
JPG/PNG，单张不超过 5MB。后端会修正照片方向、按中心裁切为 3:5、缩放为
480×800，并转换为黑、白、黄、红四色。原图不进入业务目录、数据库或对象存储；
上传请求结束后释放临时文件，只保存待确认或已经确认的四色显示图。

主要接口：

```text
GET    /v1/households/{id}/display-album
POST   /v1/households/{id}/display-album/photos
GET    /v1/households/{id}/display-album/photos/{photo_id}/image
POST   /v1/households/{id}/display-album/photos/{photo_id}/confirm
DELETE /v1/households/{id}/display-album/photos/{photo_id}
PUT    /v1/households/{id}/display-album/order
PUT    /v1/households/{id}/display-album/settings
```

相册模式开启后，设备帧只包含全屏照片，不显示食材、待办、小程序码或时间。轮播
周期可选 1、3、6、12、24 小时；设备仍按原有频率轮询，跨过轮播时间点后取得新的 ETag
和 96,000 字节原生四色帧。没有确认照片时不能开启相册；删除最后一张确认照片会
自动恢复食材清单模式。

本地开发默认使用 `data/display-photos/`。生产环境必须把
`DISPLAY_PHOTO_STORAGE_BACKEND` 设置为 `cos`，并配置同地域的私有腾讯云 COS
存储桶。小程序不直接访问 COS，所有预览必须经过后端登录态和家庭权限校验。

## 墨水屏黄历

家庭管理员和普通成员都可以通过“我的 → 水墨屏显示”在食材清单、完整简版黄历
和独立相册之间切换。黄历由服务端按 `Asia/Shanghai` 当天日期计算并渲染为全屏
480×800 逻辑画面，包括公历、星期、农历、年月日干支、生肖、节气或节日、前
4 项“宜”、前 4 项“忌”以及冲煞。界面固定显示“传统民俗，仅供参考”。

```text
GET /v1/households/{id}/display-settings
PUT /v1/households/{id}/display-settings
```

黄历模式沿用设备 HMAC、ETag、SHA-256 和 96,000 字节四色帧协议，不需要修改
ESP32 固件。同一天的内容返回稳定 ETag，日期变化后生成新版本并在下一次轮询时
刷新。第三方许可证见 `THIRD_PARTY_NOTICES.md`。

黄历天气由家庭成员在同一页面手动选择城市并启用。服务端默认每 3 小时更新一次；
获取失败时保留当天最近一次有效结果，超过 12 小时或跨日后不再显示旧天气。天气
变化会进入帧摘要并产生新 ETag。水墨屏顶部显示城市、天气、最低/最高温和降雨
概率，不在实体屏底部显示数据源文字；小程序设置区显示服务来源与网址。

本地使用固定模拟数据：

```dotenv
WEATHER_DATA_PROVIDER=mock
```

生产环境使用和风天气控制台分配的 API Host 和 Ed25519 JWT 凭据：

```dotenv
WEATHER_DATA_PROVIDER=qweather
WEATHER_REFRESH_HOURS=3
WEATHER_STALE_HOURS=12
QWEATHER_API_HOST=控制台分配的专属APIHost
QWEATHER_CREDENTIAL_ID=凭据ID
QWEATHER_DEVELOPER_ID=开发者ID
QWEATHER_PROJECT_ID=项目ID
QWEATHER_PRIVATE_KEY_BASE64=Ed25519私钥PEM的单行Base64
```

真实私钥只保存在服务端环境变量中，不得写入小程序、固件、Git 或日志。主要天气
接口为：

```text
GET /v1/households/{id}/display-settings/weather-locations?query=上海
PUT /v1/households/{id}/display-settings/weather
```

## 墨水屏一周课表

家庭管理员和普通成员都可以编辑同一家庭共享的一周课表。用户可分别设置上午、
下午节数，并为每一节配置开始和结束时间；第一版最多 10 节，每个单元格显示课程
名称和一条简短备注。小程序提供周一至周日逐日编辑和与实体屏一致的真实预览。

课表设置新增显示方向：竖屏使用现有 480×800 逻辑画面，显示今天、明天和后天；
横屏使用面板原生 800×480 画面，显示周一至周日。两种方向共用当前课程名称字号
自适应、备注、节次和时间段规则；当天列使用红色强调，当前或下一节使用黄色强调。
课表仍沿用现有 96,000 字节四色帧、HMAC、SHA-256、ETag 和 304 协议，不需要
修改 ESP32 固件。

主要接口：

```text
GET /v1/households/{id}/display-timetable
PUT /v1/households/{id}/display-timetable
GET /v1/households/{id}/display-timetable/preview
GET /v1/households/{id}/display-settings
PUT /v1/households/{id}/display-settings
```

## 墨水屏行情看板

家庭管理员和普通成员拥有相同行情管理权限。第一版每个家庭最多选择 6 项资产，
数字货币、美股、A 股和港股可按代码、中文名或英文名分别搜索，恒生/纳斯达克
指数保留为快捷选项。当前展示项可单独删除并调整顺序。刷新周期可选 15、30 或
60 分钟；
夜间暂停默认开启，在北京时间 23:00–07:00 不主动获取新行情。ESP32 仍每 5 分钟
检查一次，缓存未到期时返回稳定 ETag 和 304，不需要修改固件。

主要接口：

```text
GET /v1/households/{id}/display-market
PUT /v1/households/{id}/display-market
GET /v1/households/{id}/display-market/search
POST /v1/households/{id}/display-market/assets
DELETE /v1/households/{id}/display-market/assets/{asset_id}
GET /v1/households/{id}/display-settings
PUT /v1/households/{id}/display-settings
```

本地开发默认使用固定模拟行情：

```dotenv
MARKET_DATA_PROVIDER=mock
```

生产启用前改为 `live`，并仅在服务端配置密钥：

```dotenv
MARKET_DATA_PROVIDER=live
MARKET_SECURITY_PROVIDER=longbridge
TWELVE_DATA_API_KEY=替换为服务端密钥
COINGECKO_API_KEY=替换为服务端密钥
COINGECKO_API_KEY_TYPE=demo
COINGECKO_API_BASE_URL=https://api.coingecko.com/api/v3
LONGBRIDGE_APP_KEY=替换为模拟账户AppKey
LONGBRIDGE_APP_SECRET=替换为模拟账户AppSecret
LONGBRIDGE_ACCESS_TOKEN=替换为模拟账户AccessToken
LONGBRIDGE_HTTP_URL=https://openapi.longbridge.cn
LONGBRIDGE_QUOTE_WS_URL=wss://openapi-quote.longbridge.cn/v2
LONGBRIDGE_ENABLE_OVERNIGHT=false
LONGBRIDGE_PAPER_TRADING=true
```

CoinGecko 付费 Pro 密钥应改为：

```dotenv
COINGECKO_API_KEY_TYPE=pro
COINGECKO_API_BASE_URL=https://pro-api.coingecko.com/api/v3
```

美股、A 股、港股和指数通过 Longbridge 只读行情上下文获取，股票搜索先缓存市场
代码表，再对候选结果读取静态资料并过滤权证、行业板块等非股票标的，代码不会
创建交易上下文。数字货币通过 CoinGecko `/search` 搜索、通过 `/simple/price`
获取价格；CoinGecko 不可达时价格自动回退到 Twelve Data。
供应商失败时保留最后一次成功报价并标记“延迟”；没有缓存时显示 `--`。上线前
必须确认所购套餐包含目标交易所、所需时效和面向小程序及实体设备的展示授权，
不能把本地模拟数据用于生产。

传统 Twelve Data 证券行情仍可通过 `MARKET_SECURITY_PROVIDER=twelve_data` 回退，
但该模式不开放 A 股、港股和指数的生产承诺。

生成行情看板预览：

```bash
uv run python -m tools.render_market_preview
```
