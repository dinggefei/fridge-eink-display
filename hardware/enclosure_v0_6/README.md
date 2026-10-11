# 箱门鲜知外壳 V0.6：紧凑封闭版

V0.6 以 V0.5 已确认的硬件为基础重新设计，不覆盖或删除 V0.5。

## 设计目标

- 外轮廓由 V0.5 的 `128×200 mm` 缩小为 `120×184 mm`。
- 结构厚度由约 `29 mm` 缩小为 `21.4 mm`。这是保证最高 ESP32 器件包络仍有至少 `1.2 mm` 余量后的最薄安全值。
- 底边与四周连续封闭，所有电路板、线束和磁铁均位于壳体内部。
- 外观采用居中的竖屏窄边框、`R8` 圆角和下沉后盖螺丝。
- 顶边仅保留 Lipo Rider Plus 的 USB-C 充电口。
- BOOT/RESET 保留带凹刻文字的细工具孔，便于维护固件。

## 外形与结构

| 项目 | V0.5 | V0.6 |
|---|---:|---:|
| 外形宽度 | 128 mm | 120 mm |
| 外形高度 | 200 mm | 184 mm |
| 结构厚度 | 约 29 mm | 21.4 mm |
| 后盖器件腔 | 约 17 mm | 15.0 mm（托板上方有效 11.8 mm） |
| 底边开孔 | 已取消 | 完全封闭 |
| 磁铁 | 10×Ø10×3 mm | 10×Ø10×3 mm，全部内藏 |

V0.6 由三件组成：

1. `front_bezel_v0_6.stl`：2.4 mm 正面薄框，屏幕窗口居中。
2. `electronics_carrier_v0_6.stl`：1.6 mm 内嵌器件托板。
3. `rear_cover_v0_6.stl`：19.0 mm 连续封闭后壳。

三件由 4 颗 `M2×16 mm` 自攻螺丝从后方夹紧。螺丝头外径不得超过
`4.6 mm`、高度不得超过 `1.5 mm`，安装后应落入后盖沉孔，不得凸出。

## 现有硬件位置

- ESP32-S3：左上，四个原生孔继续使用 `M2×4 mm` 固定，天线朝上。
- Lipo Rider Plus：顶部中央，USB-C 与顶部充电孔对齐。
- DESPI-C02：右侧中部，FPC 通过内部通道连接屏幕，外侧不开放。
- 806090 电池：下半部横放，使用 0.5 mm EVA/VHB 加低矮限位条固定。

为实现 21.4 mm 厚度，ESP32 与 DESPI 之间应使用短线并压平走线；全部器件、
插头和焊点距托板上表面不得超过 `11.8 mm`。不得挤压锂电池。

## 必须先打印的检具

正式打印三大件前，依次打印：

1. `fit_test_13_4mm_assembled_height_v0_6.stl`：将已安装器件的整块托板从检具开口侧滑入，检查托板底面到最高点能否自然通过 13.4 mm。
2. `fit_test_front_corner_v0_6.stl`
3. `fit_test_carrier_corner_v0_6.stl`
4. `fit_test_rear_corner_v0_6.stl`

验收要求：

- 已安装器件的完整托板能自然通过 13.4 mm 检具，不允许强压。
- 三个角部检具按装配方向组合后，螺丝孔同轴。
- 外边缘应齐平，徒手可以装入和取出，不依靠螺丝强行拉合。
- 任一项目失败，停止打印完整三件，并反馈实测偏差。

## 文件说明

- `compact_enclosure_overview_v0_6.png`：外观与厚度效果图。
- `assembly_effect_v0_6.png`：按实际 STL 渲染的闭合、爆炸和开盖安装效果图。
- `installed_effect_v0_6.png`：安装完成后的正面与背面高清效果图。
- `exploded_view_v0_6.png`：前框、托板和后壳的高清爆炸图。
- `electronics_layout_v0_6.png`：器件、磁铁和螺丝的装配投影。
- `placement_template_v0_6_1to1.svg`：托板 1:1 位置模板。
- `manifest.json`：全部尺寸、坐标、净距和 STL 检查结果。
- `validation_report.json`：独立尺寸、封闭性、间隙和压缩包校验结果。

## 打印建议

- 材料：PETG。
- 喷嘴：0.4 mm。
- 层高：0.20 mm。
- 壁数：4。
- 顶层/底层：5。
- 填充：20% Gyroid。
- 象脚补偿：`0.15～0.20 mm`。
- 禁止自动缩放或镜像 STL。

建议正面框外观面朝下打印，中托平放，后盖外表面朝下、空腔朝上打印。

## 重新生成

```bash
../enclosure_v0_1/.venv-cad/bin/python generate_enclosure_v0_6.py
```

生成器会重新加载每个 STL，检查水密性、有效体积和单一实体。

随后运行独立校验和实际 STL 效果图渲染：

```bash
../enclosure_v0_1/.venv-cad/bin/python validate_enclosure_v0_6.py
../enclosure_v0_1/.venv-cad/bin/python render_enclosure_v0_6.py
```
