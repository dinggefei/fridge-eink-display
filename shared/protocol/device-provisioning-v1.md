# BLE 安全配网与绑定协议 v1

## 1. 安全边界

- 每台设备出厂时有唯一 `device_code` 和 256 位随机 `device_secret`。
- `device_secret` 只存在于 ESP32 固件和后端加密字段，不进入小程序、BLE 明文、
  API 响应、日志或 Git。
- 后端使用独立的 `DEVICE_SECRET_ENCRYPTION_KEY` 和 AES-256-GCM 加密保存设备
  密钥；数据库中的 SHA-256 只作指纹校验，不能替代密钥。
- 只有当前家庭管理员可以创建配网会话或解绑设备。
- Wi-Fi SSID、密码、API 地址和一次性绑定令牌在后端加密后才交给小程序；小程序
  只负责转发不透明密文。
- 配网会话默认 10 分钟失效；一个设备同时只有一个有效会话。

## 2. BLE GATT

设备广播名为 `RFM-{device_code 后 6 位}`。

| 用途 | UUID | 属性 |
|---|---|---|
| 配网服务 | `7b9e0001-5f34-4f6f-9f46-7d4c8a1e0001` | service |
| 设备编号 | `7b9e0002-5f34-4f6f-9f46-7d4c8a1e0001` | read |
| 随机挑战 | `7b9e0003-5f34-4f6f-9f46-7d4c8a1e0001` | read |
| 配网命令 | `7b9e0004-5f34-4f6f-9f46-7d4c8a1e0001` | write |
| 设备状态 | `7b9e0005-5f34-4f6f-9f46-7d4c8a1e0001` | read/notify |

随机挑战是设备每次启动配网服务时生成的 16 字节随机数，以 32 位小写十六进制
表示。它参与 AES-GCM AAD，旧密文不能在下一次配网中重放。

## 3. 后端会话

小程序读取设备编号和挑战后调用：

```http
POST /v1/households/{household_id}/devices/provisioning-sessions
Authorization: Bearer {user_token}
Content-Type: application/json

{
  "device_code": "RFM-S3-000001",
  "challenge": "32位十六进制",
  "wifi_ssid": "家庭 2.4GHz SSID",
  "wifi_password": "密码或空字符串"
}
```

响应包含 `encrypted_payload`、其 ASCII SHA-256 和 BLE UUID，不返回任何明文
Wi-Fi 配置或绑定令牌。

## 4. 密文格式

派生密钥：

```text
provisioning_key =
  HMAC-SHA256(device_secret, "rfm-provisioning-key-v1")
```

AES-GCM AAD：

```text
{device_code}\n{challenge_hex_lower}
```

明文按网络字节序编码：

```text
"RFM1"
expires_at:uint32
session_id:uint16_length + utf8
binding_token:uint16_length + utf8
api_base_url:uint16_length + utf8
wifi_ssid:uint16_length + utf8
wifi_password:uint16_length + utf8
```

最终 envelope：

```text
version 0x01 | nonce 12 bytes | AES-GCM ciphertext | tag 16 bytes
```

整个 envelope 使用无填充 Base64URL 编码。

## 5. BLE 分片

为兼容默认 20 字节 ATT MTU，每次写入不超过 20 个 ASCII 字节：

```text
B|{chunk_count}
D|{zero_based_index}|{最多12个Base64URL字符}
H|0|{SHA256第1段16字符}
H|1|{SHA256第2段16字符}
H|2|{SHA256第3段16字符}
H|3|{SHA256第4段16字符}
E
```

设备必须验证分片序号、总数、最大长度和密文 ASCII SHA-256，再执行 AES-GCM
认证解密。任一验证失败都不得尝试连接 Wi-Fi 或写入 NVS。

## 6. 完成绑定

设备联网后调用：

```http
POST /v1/devices/{device_code}/provisioning/complete
Content-Type: application/json

{
  "session_id": "UUID",
  "binding_token": "一次性随机令牌"
}
```

后端验证会话未过期、令牌 SHA-256、设备归属冲突后，原子地把设备绑定到家庭并
将会话标为 `completed`。令牌再次使用返回冲突。设备只有收到 2xx 后才能保存
Wi-Fi 和 API 地址。

## 7. 解绑、重新配网和密钥轮换

家庭管理员调用：

```http
POST /v1/households/{household_id}/devices/{device_code}/unbind
```

后端清除设备家庭归属并取消未完成会话。ESP32 本地配置不会被远程删除；再次
配网时先正常复位，串口出现提示后再单独长按 `BOOT` 2 秒，固件清除 NVS 后
重新广播 BLE。复位瞬间不得按住 `BOOT`，否则 ESP32-S3 会进入下载模式。

设备密钥轮换会立即使旧固件鉴权失效，必须在设备可刷写且已离线时执行
`python -m tools.manage_device rotate ... --confirm-device-offline`，然后把新生成
的 `device_secrets.h` 刷入该设备。
