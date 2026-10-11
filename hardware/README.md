# Hardware and enclosure models

本目录包含历代外壳的生成脚本、预览、检具和 STL。当前推荐打印版本是
[`enclosure_v0_7`](enclosure_v0_7/README.md)；`enclosure_v0_9_ultrathin`
仍属于工程验证版本。

## 建立 CAD 验证环境

```bash
uv venv hardware/.venv-cad --python 3.12
uv pip install --python hardware/.venv-cad/bin/python \
  -r hardware/requirements.txt
```

验证推荐版本：

```bash
hardware/.venv-cad/bin/python \
  hardware/enclosure_v0_7/validate_enclosure_v0_7.py
hardware/.venv-cad/bin/python \
  hardware/enclosure_v0_9_ultrathin/validate_enclosure_v0_9.py
```

自动检查只能证明模型文件符合预设尺寸与水密条件，不能替代切片、检具打印、实物
装配和锂电池安全检查。
