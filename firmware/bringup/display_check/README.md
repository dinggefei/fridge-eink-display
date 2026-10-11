# GDEM075F53 点屏自检

该程序用于验证：

- GDEM075F53 / JD79665CA 面板；
- DESPI-C02 转接板，RESE=2.2Ω；
- ESP32-S3 与 3.3V SPI 接线；
- 800×480、2 bit/像素、96,000 字节原生四色帧；
- 黑、白、黄、红四色全屏刷新。

程序只刷新一次，随后让屏幕进入深度睡眠。成功时屏幕从左到右显示黑、白、黄、
红四条竖色带，串口输出 `RESULT: PASS`。

初始化命令以 Good Display 于 2026-07-09 发布的
`A32-GDEM075F53` ESP32 示例为核对基线：

<https://www.good-display.com/companyfile/2093.html>

## 接线

| DESPI-C02 | ESP32-S3 |
| --- | --- |
| BUSY | GPIO9 |
| RES | GPIO7 |
| D/C | GPIO8 |
| CS | GPIO10 |
| SCK | GPIO12 |
| SDI | GPIO11 |
| GND | GND |
| 3.3V | 3V3 |

所有接线、拆线和 RESE 档位调整必须在 USB 断开时完成。不得连接 5V、VIN 或
VBUS。刷新过程中不得拔线或断电。
