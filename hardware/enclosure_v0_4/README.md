# 冰箱食材清单外壳 V0.4

> V0.4 的托板与后盖每边只有 0.4 mm 装配间隙，实物打印可能偏紧。完整件请改用
> [`../enclosure_v0_5/README.md`](../enclosure_v0_5/README.md) 的公差修正版。

V0.4 根据实物试摆反馈修改 V0.3：

1. ESP32-S3 向左移动，左板边距托板边缘 13 mm。
2. V0.4 后盖增加 BOOT、RESET 两个按键导向孔。
3. 顶部中央 USB-C 充电口、DESPI、FPC 和电池位置保持不变。

V0.1 只继续使用正面边框；中层托板和后盖必须同时使用 V0.4。

## 按键孔说明

- 通孔直径：5.5 mm。
- 外侧浅沉孔直径：8.5 mm，方便找到孔位并去除锐边。
- BOOT、RESET 在后盖内侧较深，不能直接用手指按。
- 使用直径 2～3 mm、端部圆滑的塑料杆按压；不要使用尖锐金属针。
- 从设备背面观察：左孔是 `BOOT`，右孔是 `RESET`。

## 打印前必须验证

1. 将 `placement_template_v0_4_1to1.svg` 以实际大小 100% 打印，确认器件位置。
2. 将 `rear_button_hole_template_v0_4_1to1.svg` 以实际大小 100% 打印，叠放在现有后盖或托板上，确认两个圆心正对按键。
3. 打印 `fit_test_button_hole_diameter_v0_4.stl`，确认准备使用的塑料按压杆能顺畅穿过。
4. 如果此前没有验证 Lipo Rider 孔位和充电插头，再打印 `fit_test_lipo_top_port_v0_4.stl`。
5. 上述检查通过后，才打印完整的 `middle_carrier_v0_4.stl` 与 `rear_cover_v0_4.stl`。

所有 SVG 打印时必须关闭“适合页面”，选择“实际大小”或“100%”。打印后先用尺测量模板外框应为对应标注尺寸。

## 建议打印参数

- PETG，0.4 mm 喷嘴，0.20 mm 层高。
- 4 道墙，顶层/底层各 5 层，25% Gyroid 填充。
- 禁止自动缩放；STL 单位为毫米。
- 中层托板大平面朝下，不加全局支撑。
- 后盖贴冰箱的一面朝下，仅对顶部充电孔按切片结果增加局部支撑。

完整安装步骤见 `ASSEMBLY_GUIDE.md`。

## 重新生成

```bash
../enclosure_v0_1/.venv-cad/bin/python generate_enclosure_v0_4.py
```

生成器会重新加载所有 STL，并验证水密性、有效体积和单一实体。
