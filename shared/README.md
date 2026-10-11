# 共享契约

该目录保存小程序、FastAPI 服务端和 ESP32 固件共同遵守的协议。

- `api/openapi.yaml`：HTTP API 基线。
- `protocol/device-frame-v1.md`：设备拉取屏幕帧的传输约定。
- `protocol/device-provisioning-v1.md`：BLE 安全配网、设备绑定和解绑约定。

共享契约先于各端实现修改。字段或状态发生不兼容变化时必须提升协议版本，
不得只修改单个客户端。
