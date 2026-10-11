# ESP32 设备签名 OTA 协议 v1

## 目标与边界

- 目标硬件：`esp32-s3-dev-kit-n16r8`，16 MB Flash、8 MB OPI PSRAM。
- OTA 只更新 ESP32 应用，不更新水墨屏数据、设备身份或 BLE 配网数据。
- 首次启用必须通过 USB 改为双 3 MB A/B 分区；之后才支持远程升级。
- 固件包必须使用 ECDSA P-256 + SHA-256 离线签名。
- 私钥永不进入服务器、设备、Git 或聊天；设备和导入工具只使用公钥。

## 请求鉴权 v2

旧固件的 HMAC v1 保持兼容。OTA 固件发送 `X-Device-Auth-Version: 2`，签名正文为：

```text
METHOD
PATH
X-Device-Timestamp
X-Device-Nonce
If-None-Match或空串
X-Device-Firmware-Version
X-Device-Firmware-Build
X-Device-Hardware
X-Content-SHA256
```

`X-Content-SHA256` 是请求体 SHA-256；无请求体时是空字节串的 SHA-256。服务端
继续校验五分钟时间窗、nonce 防重放和每台设备独立的 HMAC-SHA256 密钥。

## 检查与下载

设备仍请求：

```text
GET /v1/devices/{device_code}/frame
```

并增加 `X-Device-OTA-Capability: 1`。无更新时响应包含：

```text
X-Firmware-Update: none
```

有更新时，无论画面响应是 200 还是 304，均包含：

```text
X-Firmware-Update: available
X-Firmware-Release-Id: UUID
X-Firmware-Version: 1.0.1
X-Firmware-Build: 10001
X-Firmware-Hardware: esp32-s3-dev-kit-n16r8
X-Firmware-Size: 签名包总字节数
X-Firmware-SHA256: 签名包SHA-256
X-Firmware-Path: /v1/devices/{device_code}/firmware/{release_id}
```

设备必须逐项校验型号、构建号、长度、哈希和固定路径前缀，再使用相同 HMAC v2
鉴权下载。服务端只允许符合当前 canary/published 策略的设备读取私有文件。

## 发布状态

- `draft`：已导入但不下发。
- `canary`：只下发给明确列出的测试设备。
- `published`：明确白名单设备优先，其余按设备编号和发布 ID 的稳定哈希灰度。
- `paused`：立即停止继续下发，不强制降级已升级设备。

只允许构建号严格递增，硬件型号必须一致，并满足发布项的最小来源构建号。灰度
哈希是确定性的，同一设备不会在多次唤醒之间随机进出灰度集合。

## 设备安装与回滚

1. 下载到非当前 OTA 分区，同时计算整个签名包 SHA-256。
2. SHA-256 正确后，由 Arduino Update 验证末尾签名并设置下一启动分区。
3. 重启后的新镜像处于 `PENDING_VERIFY`，先检查 PSRAM、配置、Wi-Fi、NTP，并向
   服务端报告 `installed`。
4. 全部成功才调用 `esp_ota_mark_app_valid_cancel_rollback()`。
5. 检查失败调用 `esp_ota_mark_app_invalid_rollback_and_reboot()`，恢复上一镜像。
6. 旧镜像启动后报告 `rolled_back`。普通下载或签名失败报告 `failed`。

失败的发布 ID 和时间保存在 NVS；六小时内仍正常检查和刷新水墨屏，但不重复下载
同一失败包。下载、安装或回滚都不会覆盖设备密钥和 BLE 运行配置所在的 NVS。

## 上线顺序

1. 备份数据库和当前部署配置。
2. 部署迁移 `0009_device_ota`、私有固件持久化卷和后端代码。
3. 创建离线签名密钥；将公钥编入一台测试设备的 OTA 基础固件。
4. 通过 USB 将测试设备迁移到双 3 MB 分区并验证库存画面。
5. 制作构建号更高的签名包，以 `canary` 只发给该设备。
6. 验证下载、重启、`installed` 回报、画面刷新和五分钟 Deep-sleep 周期。
7. 再选 1–2 台设备运行至少 24 小时，随后逐步从 10% 扩到 100%。

首轮 OTA 测试必须接 USB 稳定供电。当前硬件不能可靠读取电池电量，因此本版本
不依据电量百分比决定升级；A/B 分区和签名验证是断电及坏包风险的主要保护。
