# 冰箱库存预览点屏

该程序把 `docs/assets/screen_preview_f53.png` 转换为 GDEM075F53 的
96,000 字节原生四色帧，并在实物屏幕上完整刷新一次。

生成帧文件：

```bash
python firmware/tools/png_to_f53.py \
  docs/assets/screen_preview_f53.png \
  firmware/bringup/preview_check/preview_frame.bin \
  firmware/bringup/preview_check/preview_frame.h
```

Arduino IDE 打开 `preview_check.ino` 后，使用与 `display_check` 相同的开发板、
端口和 GPIO 设置上传。刷新过程中不得拔线或断电。
