# DESPI-C02 信号线自检

该程序用于排查 ESP32-S3 到 DESPI-C02 的 `RES`、`D/C`、`CS`、`SCK`、`SDI`
五根输出线是否接通、接错或短路。它不会修改正式水墨屏固件。

## 接线

- DESPI-C02 `RES` → ESP32 GPIO7
- DESPI-C02 `D/C` → ESP32 GPIO8
- DESPI-C02 `CS` → ESP32 GPIO10
- DESPI-C02 `SCK` → ESP32 GPIO12
- DESPI-C02 `SDI` → ESP32 GPIO11
- DESPI-C02 `GND` → ESP32 GND
- DESPI-C02 `3.3V` → ESP32 3V3

## 使用前

1. 完全断电。
2. 从 DESPI-C02 中拔出水墨屏 FPC，并锁回空连接器。
3. 保留 DESPI-C02 与 ESP32 之间的跳线。
4. 上传 `display_signal_check.ino`，打开 115200 波特率串口监视器。

程序依次让每根信号线保持低电平 4 秒、高电平 4 秒。黑表笔固定接 DESPI-C02
的 GND，红表笔测串口提示的同名针脚：

- LOW 应为 0～0.2V；
- HIGH 应为 3.1～3.3V。

任意针脚不符合上述范围，都需要先修复该跳线、GPIO位置或短路问题，再连接水墨屏。
