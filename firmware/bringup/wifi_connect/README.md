# ESP32-S3 Wi-Fi 连接自检

该程序验证 ESP32-S3 能否连接指定的 2.4 GHz Wi-Fi，并从路由器获取 IPv4、
网关和 DNS 地址。程序不会刷新墨水屏。

## 配置

`secrets.h` 是只保存在本机的密码文件，已被根目录 `.gitignore` 忽略。修改：

```cpp
constexpr char kWifiSsid[] = "你的2.4GHz Wi-Fi名称";
constexpr char kWifiPassword[] = "你的Wi-Fi密码";
```

只替换双引号内部的内容，不要删除引号和分号。不要把 `secrets.h`、密码或包含
密码的截图发给任何人。

## 成功条件

串口在 30 秒内输出：

```text
Connected.
IPv4    : 192.168.x.x
RESULT: PASS
```

如果超时，优先检查 SSID 大小写、密码、2.4 GHz 是否启用，以及路由器是否启用
WPA2/WPA3 兼容模式。
