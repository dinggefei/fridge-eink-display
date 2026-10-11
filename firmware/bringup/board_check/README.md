# ESP32-S3 主控自检

该程序只检查开发板，不连接墨水屏或 DESPI-C02。

预期结果：

```text
Chip model : ESP32-S3
Flash      : 16 MB
PSRAM      : 8 MB
RESULT     : PASS
```

Arduino IDE 配置：

- Board: `ESP32S3 Dev Module`
- Port: `/dev/cu.usbmodem5B910367061`
- USB CDC On Boot: `Disabled`
- Flash Size: `16MB (128Mb)`
- PSRAM: `OPI PSRAM`
- Upload Speed: `921600`
- Serial Monitor: `115200 baud`
