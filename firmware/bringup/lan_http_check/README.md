# ESP32-S3 局域网 HTTP 自检

该程序验证完整的最小通信链路：

```text
ESP32-S3 -> 2.4 GHz Wi-Fi -> Mac -> FastAPI /health
```

程序复用 `../wifi_connect/secrets.h` 中已经填写的 Wi-Fi 配置，不会刷新墨水屏。

## 1. 启动 Mac 上的服务

在项目根目录打开终端并运行：

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

必须使用 `--host 0.0.0.0`，否则 ESP32 无法从局域网访问服务。

## 2. 确认服务地址

当前 Mac 的局域网地址已经写入 `server_config.h`：

```cpp
constexpr char kBackendBaseUrl[] = "http://192.168.1.100:8000";
```

如果 Mac 的地址改变，修改该值后重新上传程序。

## 3. 上传和检查

将 `lan_http_check.ino` 上传到 ESP32-S3，打开 115200 波特率的串口监视器，
然后按一下开发板的 `RST` 按钮。

成功输出：

```text
HTTP status : 200
Response    : {"service":"refrigerator-food-management","status":"ok"}
RESULT: PASS
```

如果 macOS 弹出“是否允许传入网络连接”，请选择“允许”。
