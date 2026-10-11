# Kindle Paperwhite 3 看板适配

本目录是 PW3（第七代 Paperwhite，1072×1448）常驻看板客户端。用户点击
资料库里的 `RFM Dashboard` 后，启动后台进程并持续显示看板；默认每 5 分钟
检查一次新画面。再次点击会要求现有进程立即刷新，不会重复启动。点击
`RFM Stop Dashboard` 会停止刷新并恢复 Kindle 的正常省电设置。

## 服务端接口

沿用设备帧路径和 HMAC v1 鉴权：

```text
GET /v1/devices/{deviceCode}/frame?format=kindle-pw3
```

签名只包含 URL path，不包含 query string，与既有设备协议一致。响应为
1072×1448 灰度 PNG，支持 ETag/304，并包含 `X-Frame-SHA256`。
Kindle 在签名前先读取 `/v1/device-time`，因此设备系统时间错误不会导致 HMAC
请求被误判为过期；ESP32 的鉴权流程保持不变。

## USB 安装结构

```text
/mnt/us/documents/RFM_Dashboard.sh
/mnt/us/documents/RFM_Stop_Dashboard.sh
/mnt/us/rfm-dashboard/config.sh
/mnt/us/rfm-dashboard/runtime.sh
/mnt/us/rfm-dashboard/start.sh
/mnt/us/rfm-dashboard/stop.sh
/mnt/us/rfm-dashboard/daemon.sh
/mnt/us/rfm-dashboard/refresh.sh
/mnt/us/rfm-dashboard/bin/rfm-power-button-exit
/mnt/us/rfm-dashboard/state/
/mnt/us/libkh/bin/fbink
```

将 `config.example.sh` 复制为 `config.sh`，填写服务地址、设备编号和设备密钥。
配置文件包含设备密钥，不得提交或分享。

`POLL_SECONDS` 控制联网检查间隔，默认 300 秒。`KEEP_AWAKE=1` 防止系统屏保
覆盖看板；停止看板时会恢复为 `0`。常驻使用应连接电源，避免持续 Wi-Fi 和禁止
自动屏保造成电量快速下降。

`HIDE_STATUS_BAR=1` 会隐藏普通状态栏。PW3 的 5.16 固件仍会由窗口管理器单独
重画左上角时间，因此 `PAUSE_WINDOW_MANAGER=1` 会在所有看板模式运行期间暂停
这一系统层，从源头去掉时间和 Wi-Fi 覆盖。配套的 `POWER_BUTTON_EXIT=1` 会监听
实体电源键：短按一次即可停止看板并恢复 Kindle 系统界面；后台进程异常结束时
监听器也会主动恢复窗口管理器。Kindle 重启仍是最后的恢复方式。

## 启动、切换和退出

1. 点击资料库里的 `RFM Dashboard`，启动入口会立即返回 Kindle 原界面。
2. 等待约 8 秒，后台进程拉取并覆盖显示最新看板。
3. 小程序切换 Kindle 的显示模式后，最多等待 `POLL_SECONDS`；也可以再次点击
   `RFM Dashboard` 请求立即刷新。
4. 需要恢复看书时，短按一次实体电源键，等待系统界面恢复。也可以在窗口管理器
   未暂停时进入资料库并点击 `RFM Stop Dashboard`。
5. 停止入口不可用时，重启 Kindle 是兜底退出方式；后台进程和防屏保设置都不会
   跨重启继续运行。

## 首次验收

1. Kindle 能访问服务地址和服务器时间接口。
2. 点击 `RFM Dashboard` 后，`state/dashboard.pid` 存在，`last-run.log` 记录
   `render_ok`；成功时不向屏幕打印文字。
3. 屏幕持续显示完整的竖版黑白看板，中文字形清楚，20 秒后不再退出。
4. 再次点击且数据未变化时，`last-run.log` 记录 `http=304`，使用缓存画面重绘。
5. 断网时保留上一张有效图片文件，不用临时文件覆盖；错误写入
   `last-error.log` 和 `state/daemon.log`，不覆盖现有看板。
6. 点击 `RFM Stop Dashboard` 后 PID 文件消失，资料库可正常操作，Kindle 可以
   正常休眠和看书。

常驻模式不把下载错误打印到屏幕，以免临时断网覆盖上一张有效看板。同一信息会
保存在 `/mnt/us/rfm-dashboard/last-error.log`，详细运行输出在
`/mnt/us/rfm-dashboard/state/daemon.log`，便于通过 USB 复查。

## 当前边界

- 当前已启用后台五分钟轮询，但尚未启用开机自启；Kindle 重启后需要再次点击
  `RFM Dashboard`。
- 脚本依赖 Kindle 上的 `curl`、`openssl`、`sha256sum` 和现有 FBInk。
- 真实 PW3 上需要验收后台进程能否在 Scriptlet 返回后继续运行、停止入口、模式
  切换、屏幕方向、灰阶、手动锁屏恢复和长时间耗电。

## 客户端回归验证

运行 `python3 -m unittest discover -s kindle/tests -v`，验证首次下载、第二次打开、
旧 CRLF 缓存、损坏缓存、缓存图片缺失、显示工具失败，以及后台启动、立即刷新、
防重复进程和停止流程。测试中的替代 FBInk 会校验实际命令行参数和日志隔离；
它仍不等于硬件显示验证，常驻生命周期仍需在 Kindle 上验收。

## 2026-09-25 显示错误诊断

- 设备实际 FBInk 为 1.25.0，二进制 SHA-256 为
  `3cceba4168a9d2e3692026221c7bd81e1567f38d78c49818371541d2246b77e7`。
- 使用此二进制在 QEMU ARM 用户态执行，帮助信息确认 `Image=Yes`。
- 旧命令 `-g /path/frame.png` 返回参数解析错误；正确写法为
  `-g file=/path/frame.png`，或 `-i /path/frame.png`。
- 同一真实二进制验证修正参数后已进入 framebuffer 打开阶段；模拟环境没有
  `/dev/fb0`，因此无法替代真机刷屏验收。
- 设备缓存 PNG 已通过文件解码校验：1072×1448、L 灰度。
- 显示调用的完整 stdout/stderr 写入 `state/fbink.log`，避免帮助文字覆盖图片。
  渲染失败时保留退出码与具体错误；不会把新 ETag 标记为显示成功。
- Scriptlet 退出会触发原界面刷新；常驻版让后台进程延迟约 8 秒后绘制，避开这次
  原界面刷新。启动与停止入口都使用 `DontUseFBInk`，不会把启动器控制台文字覆盖
  到看板上。

参考：[FBInk 命令实现](https://github.com/NiLuJe/FBInk/blob/master/fbink_cmd.c)、
[Scriptlet 启动器](https://github.com/KindleModding/sh_integration/blob/master/launcher/main.c)。
