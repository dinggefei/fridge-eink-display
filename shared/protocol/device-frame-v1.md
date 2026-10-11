# 设备屏幕帧协议 v1

## 1. 请求

设备启动后立即请求一次，成功后每 5 分钟请求：

```http
GET /v1/devices/{deviceCode}/frame
```

请求头：

| 请求头 | 要求 |
|---|---|
| `If-None-Match` | 已缓存帧的 ETag；首次请求省略 |
| `X-Device-Timestamp` | Unix 秒时间戳，与服务端时间误差不得超过 300 秒 |
| `X-Device-Nonce` | 每次请求生成的新随机值，至少 16 个字符 |
| `X-Device-Signature` | HMAC-SHA256 小写十六进制签名 |

签名原文严格按以下顺序拼接，每一项之间使用一个换行符，末尾不加换行：

```text
GET
/v1/devices/{deviceCode}/frame
{X-Device-Timestamp}
{X-Device-Nonce}
{If-None-Match；没有时为空字符串}
```

签名计算：

```text
hex_lower(HMAC_SHA256(device_secret, signing_text))
```

服务端拒绝过期时间戳、重复 nonce 和签名不匹配的请求。nonce 至少保留
10 分钟用于防重放。

Wi-Fi、时间同步、HTTP、完整性校验或刷新失败时，设备应保留当前画面并按
5 秒、15 秒、60 秒、300 秒的间隔逐级重试。任意一次成功后清零失败计数并恢复
每 5 分钟轮询。

## 2. 有新画面

服务端返回：

```http
HTTP/1.1 200 OK
Content-Type: application/octet-stream
Content-Length: 96000
ETag: "frame-{version}"
X-Frame-Version: {version}
X-Frame-SHA256: {64位小写十六进制摘要}
X-Panel-Model: GDEM075F53
X-Display-Orientation: portrait
```

设备必须按顺序完成以下检查：

1. HTTP 状态为 `200`。
2. `X-Panel-Model` 等于设备配置的 `GDEM075F53`。
3. `Content-Length` 等于 `96000`。
4. 实际接收长度等于 `96000`。
5. 实际内容 SHA-256 等于 `X-Frame-SHA256`。
6. 全部通过后写入临时缓存。
7. 临时缓存写入成功后替换上一帧并刷新屏幕。

服务端始终返回 GDEM075F53 的 800×480 原生传输顺序。普通模式以及课表竖屏
模式在服务端先按 480×800 排版再旋转，并返回 `portrait`；课表横屏模式直接按
800×480 排版并返回 `landscape`。设备直接发送完整原生帧，不在 ESP32 端二次
旋转。

任一检查失败时必须保留上一帧。

## 3. 画面未变化

ETag 一致时服务端返回：

```http
HTTP/1.1 304 Not Modified
```

响应没有消息体。设备不得重复刷新墨水屏。

设备只允许在新画面完成校验并且屏幕刷新成功后保存新的 ETag。ETag 应持久化，
使设备断电重启后仍能发送 `If-None-Match`。如果下载、校验或刷新失败，必须继续
保留上一帧的 ETag，以便下次启动重新请求新画面。

## 4. 帧编码边界

传输层固定为 96,000 字节的设备原生帧。GDEM075F53 的字节内像素顺序和
四色编码将在使用厂家 F53 示例完成首次点屏后锁定为
`gdem075f53-native-v1`。在该实测完成前，服务端不得发布生产帧；不得沿用
GDEM075F52/JD79665AA 的编码假设。
