# 设备一键出厂工具

本工具用于把一块新的 ESP32-S3 和墨水屏制作成可出售、未绑定的独立设备。
它不会替代硬件测试，也不会自动读取 ESP32 的 NVS；物理测试和清除配置必须由
操作人员确认。

## 1. 一条命令生成的内容

`tools.factory_device create-batch` 会原子地完成：

- 生成唯一公开设备编号，默认格式为 `rfm-年份后两位-随机六位`。
- 为每台设备生成独立的 256 位随机密钥。
- 把密钥指纹和 AES-256-GCM 加密密文写入当前数据库。
- 将设备注册为 `unbound`，不归属任何家庭。
- 调用微信官方接口生成携带设备编号的真实小程序码。
- 将小程序码缓存到设备数据库记录。
- 为每台设备生成专属 `device_secrets.h`。
- 为每台设备生成专属 `factory_pairing_frame.h` 和绑定画面预览图；未绑定且
  尚未配网时，固件可直接在水墨屏上显示该设备的小程序码。
- 生成单张 PNG 标签、A4 标签 PNG 和多页 PDF。
- 生成不含设备密钥的 JSON、CSV 批次清单。

单个批次最多 20 台；更多设备应拆分为多个批次，便于复核、返工和限制生产密钥
暴露范围。

任一步失败时，数据库事务回滚，刚创建的批次目录也会删除，不会留下半成品。

## 2. 安全规则

- 工具从当前 `.env` 解析数据库、微信 AppID/AppSecret 和设备密钥加密主密钥。
- 准备出售的设备必须在生产数据库执行，不能只注册到开发数据库。
- 输出目录必须是不存在的新目录；工具拒绝覆盖旧批次。
- 批次目录和设备子目录权限为 `0700`。
- `device_secrets.h` 权限为 `0600`。
- 密钥不会输出到终端、标签、JSON 或 CSV。
- `device_secrets.h` 不得提交 Git、发送给购买者或放入普通网盘。
- 设备编号是公开信息，应印在永久标签上。

## 3. 本地开发演练

以下命令连接 `backend/.env` 指向的数据库。使用
`--skip-mini-program-code` 只适合测试工具，不可用于出售设备：

```bash
cd /path/to/RefrigeratorFoodManagement/backend

uv run python -m tools.factory_device create-batch \
  --count 1 \
  --code-prefix rfm-26 \
  --output-dir /path/to/DeviceFactory/test-batch-001 \
  --skip-mini-program-code
```

也可以指定一个明确编号：

```bash
uv run python -m tools.factory_device create-batch \
  --device-code rfm-demo-001 \
  --output-dir /path/to/DeviceFactory/test-batch-002 \
  --skip-mini-program-code
```

开发演练会真实写入当前开发数据库。已经注册的编号不能再次使用。

## 4. 生产批次生成

生产设备必须在腾讯云服务器上使用生产配置注册。先通过 SSH 登录服务器，进入
生产部署目录，并创建仅部署用户可访问的持久化输出目录：

```bash
cd /服务器项目路径/infra/production

mkdir -p factory-output
chmod 700 factory-output

docker compose run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/factory-output:/factory-output" \
  backend \
  python -m tools.factory_device create-batch \
  --count 5 \
  --code-prefix rfm-26 \
  --output-dir /factory-output/rfm-factory-batch-001
```

生产命令默认要求微信真实小程序码生成成功。不要添加
`--skip-mini-program-code`。

文件会保存在服务器宿主机的
`infra/production/factory-output/rfm-factory-batch-001`，不会因为临时后端
容器退出而消失。生成后，将整个批次目录通过 SSH 安全复制到制造电脑的私有
目录。复制完成后先核对文件数量和 `manifest.json`，不要立即删除服务器上的
原始批次。

批次目录结构示例：

```text
rfm-factory-batch-001/
├── manifest.json
├── manifest.csv
├── labels-a4-page-01.png
├── labels-a4.pdf
└── rfm-demo-001/
    ├── device_secrets.h
    ├── factory_pairing_frame.h
    ├── factory-pairing-frame.png
    ├── mini-program-code.png
    └── device-label.png
```

超过 10 台设备时会生成多张 `labels-a4-page-NN.png`，PDF 包含全部页面。

## 5. 固件烧录

每次只能为当前准备烧录的那台设备暂存一个 `device_secrets.h`：

1. 从批次目录选择设备，例如 `rfm-demo-001`。
2. 将它的 `device_secrets.h` 和 `factory_pairing_frame.h` 复制到：

   ```text
   firmware/bringup/frame_download_display/device_secrets.h
   firmware/bringup/frame_download_display/factory_pairing_frame.h
   ```

3. 在 Arduino IDE 重新打开 `frame_download_display.ino`。
4. 编译并上传到对应的新 ESP32-S3。
5. 打开 115200 串口，确认广播名称最后六位与设备标签一致：

   ```text
   No saved configuration; starting secure BLE setup.
   BLE provisioning ready: RFM-a7k3p9
   ```

   新设备还应先刷新专属绑定画面，并打印：

   ```text
   PAIRING DISPLAY: showing this device's mini-program code.
   PAIRING DEVICE: rfm-demo-001
   ```

6. 立即把同一个 `device-label.png` 对应的标签贴到该设备，防止串号。
7. 换下一台设备前，替换为下一台的头文件。

固件暂存路径被 Git 忽略，但仍应在制造电脑上限制访问。批次目录是后续维修、
固件升级和密钥轮换的重要生产资料。

## 6. 出厂测试

每台设备至少完成：

- ESP32-S3、Flash、PSRAM 自检。
- GDEM075F53 四色刷新测试。
- BLE 广播和真机连接。
- 2.4GHz Wi-Fi 连接。
- 正式后端绑定完成回调。
- 正式设备接口鉴权。
- 96,000 字节画面下载、校验和实屏刷新。
- 标签小程序码扫码进入正确设备页面。
- 水墨屏上的小程序码能够扫码，并进入与标签一致的设备页面。

如果测试时绑定到工厂测试家庭，测试完成后必须：

1. 在小程序中解除该设备绑定。
2. 按一下 `RST`。
3. 串口出现提示后，单独长按 `BOOT` 2 秒清除 NVS。
4. 再次启动并确认出现 `No saved configuration` 和
   `BLE provisioning ready`。
5. 确认墨水屏已恢复为该设备专属的小程序码绑定画面，不再保留测试家庭内容。

## 7. 强制出厂检查

先在生产环境查看设备公开状态：

```bash
docker compose exec backend \
  python -m tools.factory_device list --limit 100
```

完成物理测试和 NVS 清除后，对每台设备执行：

```bash
docker compose run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "$PWD/factory-output:/factory-output" \
  backend \
  python -m tools.factory_device release-check \
  --device-code rfm-demo-001 \
  --artifact-dir /factory-output/rfm-factory-batch-001/rfm-demo-001 \
  --confirm-hardware-pass \
  --confirm-nvs-cleared
```

只有最后出现以下结果才可以包装：

```text
RELEASE CHECK: PASS
```

检查会验证：

- 设备已注册且状态为 `unbound`。
- 不归属任何家庭。
- 加密设备密钥存在。
- 微信小程序码已缓存。
- 没有未完成的配网会话。
- 固件头文件属于正确设备且权限为 `0600`。
- 可打印标签存在。
- 操作人员已确认硬件测试和 NVS 清除。

工具无法通过网络证明某一块实体板已使用对应固件，因此烧录后立即贴标签和扫描
核对仍是必须的人工工序。

## 8. 交付物

购买者只能获得：

- 已装配并清除配置的设备。
- 带设备编号和微信小程序码的永久标签。
- USB-C 供电说明和简明使用说明。

购买者不得获得：

- `device_secrets.h`。
- 设备密钥、数据库密钥或微信 AppSecret。
- 工厂测试账号和 Wi-Fi 信息。

首次销售前还必须完成小程序备案、ICP 备案、生产 HTTPS、微信合法域名和正式版
小程序发布。开发版二维码和局域网 API 不能作为商品交付方案。
