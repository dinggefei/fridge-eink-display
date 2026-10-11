# V0.9 STL 打印包

本包是独立 V0.9 工程样机，不会覆盖 V0.7。正式外壳目标尺寸为 120 × 184 × 15.0 mm。

中托普通区厚 1.2 mm，电池下方底板厚 0.6 mm；后盖普通面厚 1.0 mm，磁片外侧厚 0.6 mm，左侧补强带厚 1.2 mm。

ESP32 螺丝柱高出中托表面 1.4 mm（柱顶模型 Z=2.6 mm），Lipo Rider 螺丝柱高出中托表面 0.6 mm（柱顶模型 Z=1.8 mm）；Lipo Rider 对应的 Type-C 开口中心为后盖模型 Z=6.6 mm。

电池与磁片槽之间的名义余量为 0.8 mm；电池连同转移胶实测总厚度不得超过 8.2 mm。

后盖的 BOOT、RESET 已改为半封闭悬臂按键：周围开 270°、宽 0.8 mm 的圆弧贯穿槽，上方保留 90°、厚 0.4 mm 的连接桥；内侧 Ø1.8 mm 按压杆从后盖内表面伸出 4.5 mm，杆端带 0.2 mm 倒角，名义静止间隙为 0.7 mm，不再凹刻文字。

Lipo Rider 指示灯开孔保持下边缘不动，上边缘下移 3 mm；R1 圆角之间的直边由 19 mm 改为 16 mm，总开孔为 5.2 × 18 mm、R1 mm。

## 首先打印

1. `fit_test_front_corner_v0_9_1p0mm.stl`：验证 1.0 mm 前框、加强区和 M2×12 螺丝。
2. `fit_test_usb_c_opening_11p5x7p5_v0_9.stl`：验证低位 Lipo Rider 对准 Type-C 公头。

3. `fit_test_boot_reset_buttons_4p5mm_v0_9.stl`：装上 ESP32 后确认两根按压杆是否能分别触发 BOOT、RESET，且合盖后没有持续压住开关。
4. `fit_test_lipo_indicator_opening_5p2x18_v0_9.stl`：确认缩短后的窗口满足实际指示灯观察范围。

四个检具均通过后，再打印前三个正式零件。Type-C 净开口保持 V0.7 的 11.5 × 7.5 mm。
