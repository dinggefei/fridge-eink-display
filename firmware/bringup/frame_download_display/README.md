# 下载服务端画面并刷新 GDEM075F53

该程序完成第一条真实画面链路：

```text
FastAPI -> HTTP -> ESP32-S3 PSRAM -> SHA-256 校验 -> GDEM075F53
```

设备先通过 NTP 同步 Unix 时间，为每个请求生成新的 128 位随机 nonce，并使用
本地设备密钥计算 HMAC-SHA256。服务端拒绝设备编号错误、时间过期、nonce 重放
或签名不正确的请求。

Wi-Fi 和服务端地址不再写死在源码中。首次启动时，固件开启 BLE 配网服务，
由微信小程序发送经过设备出厂密钥 AES-GCM 加密的配置。配置只有在设备成功联网
并完成后端绑定后才保存到 NVS。`device_secrets.h` 只保留每台设备唯一的出厂编号
和 64 位随机密钥。

正式出厂固件还应包含由出厂工具为同一设备生成的
`factory_pairing_frame.h`。设备没有运行配置时，会先在水墨屏显示该设备专属的
小程序码，再启动 BLE 配网。显示成功后由 NVS 记录状态，普通重启不会反复刷新
同一画面。绑定成功并下载正式画面后，该记录会清除，以便以后解除绑定时重新
显示小程序码。

生产 API 使用 HTTPS 时，固件只信任随源码固定的 ISRG Root X1，不使用
`setInsecure()`。配网联网后先同步时间，再验证 TLS 证书和会话有效期。当前根证书
来源及指纹记录在 `tls_roots.h`；更换证书签发机构时必须同步更新并重新编译。

## 操作

1. 在 Mac 上启动 FastAPI：

   ```bash
   cd /path/to/RefrigeratorFoodManagement/backend
   uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. 浏览器打开 `http://192.168.1.100:8000/v1/bringup/frame`（替换为你的后端地址）。浏览器下载一个
   96,000 字节文件属于正常现象。
3. 在 Arduino IDE 中打开 `frame_download_display.ino` 并上传。
4. 打开 115200 波特率串口监视器，按一下 `RST`。
5. 看到 `BLE provisioning ready` 后，在小程序“我的 → 墨水屏设备”填写设备
   编号和 2.4GHz Wi-Fi，点击“开始绑定”。
6. 从开始刷新起不得拔线或断电，等待屏幕显示冰箱库存。

已经保存配置时，先只按一下 `RST` 正常启动。串口出现
`Saved configuration found` 后，再单独按住 `BOOT` 2 秒；看到清除提示后松开。
不要在按住 `BOOT` 时复位，否则 ESP32-S3 会进入 `waiting for download`。

设备没有保存配置，但串口显示
`PAIRING DISPLAY: already shown`、水墨屏却没有小程序码时，先按一下 `RST`，
等待串口出现 `Pairing display already recorded`，再单独按住 `BOOT` 2 秒。
看到 `forcing pairing display refresh` 后松开，设备会重新刷新专属小程序码，
不需要擦除 Flash 或重新烧录。此操作同样不要与 `RST` 同时按下。

设备在小程序中解除绑定后，后端画面接口会返回
`X-Device-State: unbound`。固件在下一次五分钟唤醒时会清除本地 Wi-Fi、API、
ETag 和家庭配置，恢复专属小程序码画面并重新进入 BLE 配网；按一下 `RST` 可以
提前触发这次状态检查。服务端不可达或普通 HTTP 错误不会触发清除。

只有 HTTP 状态、面板型号、声明长度、实际长度和 SHA-256 全部正确时，程序才会
刷新屏幕。刷新成功后，程序把服务端 ETag 保存到 ESP32 的 NVS。

首次运行或画面改变时：

```text
HTTP status: 200
ACTION: REFRESHED
RESULT: PASS
```

不修改服务端画面，直接再次按 `RST`，应看到：

```text
HTTP status: 304
ACTION: SKIP_REFRESH
RESULT: PASS
```

第二次运行时屏幕不得闪烁或刷新。NVS 在普通断电和重新上传固件后仍会保留，
因此相同画面不会被重复刷新。

## 屏幕刷新完成判定

GDEM075F53 收到刷新命令后，`BUSY` 不一定立即拉低。固件会先确认 `BUSY`
已经拉低（刷新真正开始），再等待它恢复高电平（刷新真正结束），最后才保存
ETag、关闭面板并进入 Deep-sleep。正常刷新日志应包含：

```text
8/8 Refreshing; do not disconnect power...
    BUSY asserted after ... ms; waiting for full refresh to finish...
    full refresh completed in ... ms.
Saved ETag : "inventory-..."
ACTION: REFRESHED
RESULT: PASS
```

若 3 秒内 `BUSY` 没有拉低，固件会输出
`ERROR: BUSY never asserted during full refresh.`，不会保存新 ETag，并进入失败重试。
此时应检查 DESPI-C02 的 `BUSY` 到 ESP32-S3 GPIO 9 的接线。

完整刷新结束后的 `0x02` 面板关电命令存在两种正常 BUSY 行为：部分控制器会再次
拉低 BUSY，部分控制器会始终保持空闲高电平。固件会观察 500 毫秒；检测到低电平
时等待其恢复，始终保持高电平时也继续进入面板休眠。该兼容处理只用于关电命令，
不会放宽上电和完整刷新阶段的严格 BUSY 校验。

本次修复将 ETag 缓存键升级为 `etag-v2`。因此刷入该版本后的第一次启动会忽略
旧固件保存的 ETag，强制下载完整画面并执行一次真实刷新；后续仍会正常使用
HTTP 304 跳过未变化的画面。

## 低功耗自动轮询与失败重试

固件启动后立即检查一次。每次检查结束后会关闭 Wi-Fi，并让 ESP32-S3 进入
Deep-sleep；5 分钟后由硬件定时器唤醒，再执行一次检查：

```text
RESULT: PASS
NEXT WAKE: 300 seconds
DEEP SLEEP: 300 seconds
Wi-Fi off; ESP32 entering deep sleep now.
```

定时唤醒时会看到：

```text
Wake reason: DEEP_SLEEP_TIMER
```

这是正常的重新启动过程。定时唤醒会跳过冷启动时长达 8 秒的配网重置等待窗口，
不会每 5 分钟白白等待。只有上电、重新刷写或按下 RST 后，才会显示
`COLD_OR_RESET` 并允许在提示出现后长按 BOOT 2 秒清除配置。

从 `1.1.1（build 11001）` 开始，冷启动、复位、OTA 新镜像自检以及距上次校时
满 1 小时时会执行一次 NTP 校时。其余五分钟定时唤醒会复用 Deep-sleep 保留的
RTC 时间，避免每个周期都等待 NTP。执行 NTP 时日志包含：

```text
2/8 Synchronizing time from NTP...
    NTP synchronized: ...
```

复用 RTC 时间时日志包含：

```text
2/8 Retained clock ready: ... (last NTP ... seconds ago)
```

若服务端返回 `HTTP status: 401` 且本周期尚未执行 NTP，固件会立即强制校时并只
重试一次请求；这样既保持服务端 300 秒签名窗口，也不会因长期 RTC 漂移而停止
更新。

首次完整连接成功后，固件会把 Wi-Fi 信道和 BSSID 保存在 RTC 内存中。后续唤醒
先尝试 2.5 秒快速连接；若路由器更换、信道变化或快速连接失败，会自动退回完整
Wi-Fi 连接，不需要用户重新配网。正常快速连接日志包含：

```text
1/7 Fast Wi-Fi connect on cached channel ...
    Wi-Fi ready in ... ms (fast path).
```

Wi-Fi、NTP、HTTP、数据校验或屏幕刷新任一环节失败时，固件不会改变已显示画面，
也不再按 5/15/60 秒高频唤醒。成功和失败均保持 300 秒检查周期；失败日志会附带
连续失败次数：

```text
RETRY WAKE: 300 seconds (failure streak=...)
```

任意一次成功后，失败计数清零。

若服务端返回 `HTTP status: 304`，说明画面未变化。固件不会唤醒水墨屏，关闭
Wi-Fi 后直接进入 Deep-sleep：

```text
ACTION: SKIP_REFRESH
RESULT: PASS
NEXT WAKE: 300 seconds
DEEP SLEEP: 300 seconds
```

串口监视器在 Deep-sleep 期间没有新输出属于正常现象；约 5 分钟后应重新出现
ESP-ROM 启动信息和 `Wake reason: DEEP_SLEEP_TIMER`。

首次没有保存配置时，设备必须保持 BLE 广播以等待小程序配网，因此这一阶段不会
进入 Deep-sleep。配网和后端绑定成功后才开始低功耗循环。

固件使用带 HMAC-SHA256 签名的正式设备接口：

```text
GET /v1/devices/rfm-demo-001/frame
```

`device_secrets.h` 与后端 `.env` 已在本机生成且被 Git 忽略。不要分享这两个
文件或设备密钥。

## 签名 A/B OTA

该版本支持每次 Deep-sleep 唤醒后先通过画面接口检查 OTA。若存在匹配硬件且高于
当前构建号的灰度版本，设备会先下载签名包到未运行的 OTA 分区，校验下载
SHA-256 和 ECDSA P-256 固件签名，然后切换分区并重启。新固件只有在 PSRAM、
运行配置、Wi-Fi、NTP 和服务端安装回报全部成功后才会标记有效；否则由 ESP32
引导程序恢复到上一分区。OTA 失败不影响本轮正常画面刷新，同一失败版本六小时内
不再重复下载。

首次启用 OTA 必须通过 USB 完成一次分区迁移。在 Arduino IDE 中选择：

```text
Board: ESP32S3 Dev Module
Flash Size: 16MB (128Mb)
PSRAM: OPI PSRAM
Partition Scheme: 16M Flash (3MB APP/9.9MB FATFS)
Erase All Flash Before Sketch Upload: Disabled
```

旧的默认分区单个 APP 槽只有约 1.25 MiB，当前固件已经接近上限，不能直接接收
OTA。新的分区包含 `ota_0`、`ota_1` 两个 3 MiB 槽和 `otadata`。首次 USB
迁移必须先选对上述分区再烧录；建议先对一台测试设备操作，并保持 USB 供电完成
首次启动验证。

设备必须内置签名公钥。用 Arduino-ESP32 随附的 `bin_signing.py` 离线生成一组
ECDSA P-256 密钥，把生成的 `ota_public_key.h` 放到本目录。私钥只能保存在离线
安全目录，不能进入 Git、服务器、ESP32、截图或聊天。仓库中的
`ota_public_key.h.example` 只是格式说明；缺少真实公钥时固件仍可编译和刷新
画面，但会明确拒绝 OTA。

每个正式升级版本必须同时修改源码中的 `kFirmwareVersion` 和递增的
`kFirmwareBuildNumber`，再导出 Arduino 已编译二进制，用同一私钥签名：

```bash
python /Arduino-ESP32绝对路径/tools/bin_signing.py \
  --bin frame_download_display.ino.bin \
  --key /离线安全路径/ota-private-key.pem \
  --out /安全路径/frame_download_display-signed.bin
```

签名包最后包含 512 字节签名区，不能把未签名 `.bin` 导入后端。服务端发布流程和
灰度命令见 `../../../backend/README.md`，协议细节见
`../../../shared/protocol/device-ota-v1.md`。

## 低功耗验收

重新刷写后必须连续验证两个周期：

1. 第一个周期能联网并得到 `RESULT: PASS`。
2. 随后出现 `NEXT WAKE: 300 seconds` 和 `DEEP SLEEP: 300 seconds`。
3. 休眠期间串口没有循环打印，也不应出现反复联网。
4. 约 5 分钟后出现 `Wake reason: DEEP_SLEEP_TIMER`。
5. 未修改库存时得到 `HTTP status: 304` 和 `ACTION: SKIP_REFRESH`。
6. 定时唤醒时不得出现 `Saved configuration found. To clear it...` 的 8 秒等待提示。
7. 第二次定时唤醒应优先出现 `Fast Wi-Fi connect` 和
   `Retained clock ready`，并输出 `CYCLE ELAPSED: ... ms`。
8. 断开路由器后应直接输出 `RETRY WAKE: 300 seconds`，不得出现 5 秒、15 秒或
   60 秒快速重试。

通过以上检查后，再断开电脑，使用 Lipo Rider 和 806090 电池连续运行并记录：

- 开始时间与满电状态；
- 每天是否正常更新；
- 完全没电时间；
- 若有 USB 电流表，同时记录运行电流和 Deep-sleep 电流。
