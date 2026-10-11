# 生产部署

目标环境：腾讯云中国大陆轻量应用服务器，Ubuntu 24.04，2 核 2GB。

## 资源边界

- Caddy 负责 HTTPS 和反向代理。
- FastAPI 仅通过 Caddy 对外提供服务。
- PostgreSQL 不映射公网端口。
- FastAPI 的 `8000` 端口只监听服务器本机，便于 SSH 登录后检查。
- PostgreSQL 限制为 512MB，适合当前小流量 MVP。
- 独立 recognition worker 默认最多并发 2 个外部模型请求，不在 2GB
  服务器上运行大模型。
- 订单原图位于 API 与 worker 共享的临时 Docker 卷，不进入数据库备份。
- 只在腾讯云防火墙开放 `22`、`80`、`443`。

## 服务器购买后

先在腾讯云控制台绑定 SSH 密钥，不要通过聊天传输密码或私钥。登录服务器后，
按照 Docker 官方 Ubuntu 安装文档配置 Docker APT 仓库并安装以下软件包：

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

将部署用户加入 `docker` 用户组后退出 SSH 并重新登录，让用户组生效。然后克隆
或同步项目并进入生产目录。

腾讯云中国大陆服务器访问 Docker Hub 超时时，可按腾讯云官方镜像加速说明在
`/etc/docker/daemon.json` 配置：

```json
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com"
  ]
}
```

修改后先验证配置，再重启 Docker：

```bash
sudo dockerd --validate --config-file=/etc/docker/daemon.json
sudo systemctl restart docker
```

## 生成生产配置

```bash
cd infra/production
cp production.env.example .env
chmod 600 .env
openssl rand -hex 32
```

把随机值分别用于 `POSTGRES_PASSWORD`、`AUTH_TOKEN_SECRET` 和
`DEVICE_SECRET_ENCRYPTION_KEY`，三次分别生成。设备密钥加密键必须与登录令牌
密钥分开，后续轮换登录密钥不会导致设备凭据无法解密。
不要把 `.env`、微信 AppSecret、设备密钥或 SSH 私钥提交到 Git。

在腾讯混元控制台开通服务并创建 **OpenAI 兼容 API Key**。它以 `sk-` 开头，
不同于腾讯云 SecretId/SecretKey。将 API Key 只填写到服务器 `.env`：

```dotenv
RECOGNITION_PROVIDER=hunyuan
RECOGNITION_EXECUTION_MODE=worker
RECOGNITION_IMAGE_CONCURRENCY=2
HUNYUAN_API_KEY=sk-替换为真实值
```

不要在聊天、小程序代码或 Git 中发送该密钥。本地开发继续使用 `mock`，生产环境
会拒绝以 `mock` 启动，避免把模拟商品写入真实库存。

中国大陆服务器构建容器时，保留示例配置中的：

```dotenv
PYPI_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
```

海外服务器可改回 `https://pypi.org/simple`。

## 配置私有照片存储

墨水屏相册上线前，必须在腾讯云 COS 创建一个与轻量服务器同地域的存储桶，并将
访问权限设置为“私有读写”。为后端创建只允许该存储桶对象读、写、删除的最小权限
子账号密钥，不要使用主账号永久密钥。然后在生产 `.env` 填写：

```dotenv
DISPLAY_PHOTO_STORAGE_BACKEND=cos
DISPLAY_PHOTO_MAX_IMAGE_BYTES=5242880
DISPLAY_PHOTO_MAX_PHOTOS=6
COS_REGION=存储桶地域，例如 ap-shanghai
COS_BUCKET=完整存储桶名称，包含 AppID 后缀
COS_SECRET_ID=后端专用子账号 SecretId
COS_SECRET_KEY=后端专用子账号 SecretKey
```

存储桶不需要配置公共读权限、静态网站或小程序合法域名。照片预览由 FastAPI 在
验证微信登录态和家庭成员关系后返回。上线前先执行数据库迁移 `0008_display_album`，
再启动新容器；缺少 COS 配置时生产后端会拒绝启动，避免误把家庭照片落到容器本地。

## 配置行情数据源

行情看板在本地默认使用模拟数据。生产环境由 CoinGecko 提供数字货币首选行情、
Twelve Data 提供数字货币网络回退，Longbridge 提供美股、A 股、港股和指数行情。
在生产 `.env` 填写：

```dotenv
MARKET_DATA_PROVIDER=live
MARKET_SECURITY_PROVIDER=longbridge
TWELVE_DATA_API_KEY=替换为真实密钥
TWELVE_DATA_API_BASE_URL=https://api.twelvedata.com
COINGECKO_API_KEY=替换为真实密钥
COINGECKO_API_KEY_TYPE=demo
COINGECKO_API_BASE_URL=https://api.coingecko.com/api/v3
LONGBRIDGE_APP_KEY=替换为模拟账户AppKey
LONGBRIDGE_APP_SECRET=替换为模拟账户AppSecret
LONGBRIDGE_ACCESS_TOKEN=替换为模拟账户AccessToken
LONGBRIDGE_HTTP_URL=https://openapi.longbridge.cn
LONGBRIDGE_QUOTE_WS_URL=wss://openapi-quote.longbridge.cn/v2
LONGBRIDGE_ENABLE_OVERNIGHT=false
LONGBRIDGE_PAPER_TRADING=true
MARKET_DATA_TIMEOUT_SECONDS=12
```

如果申请的是 CoinGecko 付费 Pro 密钥，将类型与域名改为：

```dotenv
COINGECKO_API_KEY_TYPE=pro
COINGECKO_API_BASE_URL=https://pro-api.coingecko.com/api/v3
```

密钥只放在权限为 `600` 的生产 `.env`，不得写入小程序、固件、Git 或日志。部署
迁移 `0012_market_display` 后，先用测试家庭验证代码、币种、数据时效、缓存
和错误回退，再允许正式家庭选择行情模式。没有配置真实供应商时不得启用生产行情。
中国大陆服务器无法连接 CoinGecko 时，服务端会自动通过 Twelve Data 获取
`BTC/USD` 与 `ETH/USD`，但仍应保留 CoinGecko 配置以便网络恢复后自动使用首选源。
Longbridge 仅创建 `AsyncQuoteContext`，不创建交易上下文。部署后必须分别验证
`AAPL.US`、`600519.SH`、`700.HK`、`HSI.HK` 和 `.IXIC.US`，并确认返回时间与当前
账户的 OpenAPI 行情权限一致。三个 Longbridge 凭证不得写入日志或测试输出。

## 配置黄历天气数据源

黄历天气使用和风天气服务端 API。先在控制台创建项目和 Ed25519 凭据，并取得该
项目的专属 API Host。把私钥 PEM 转成单行 Base64 后，仅写入权限为 `600` 的生产
`.env`：

```dotenv
WEATHER_DATA_PROVIDER=qweather
WEATHER_REFRESH_HOURS=3
WEATHER_FAILURE_RETRY_MINUTES=15
WEATHER_STALE_HOURS=12
WEATHER_DATA_TIMEOUT_SECONDS=12
QWEATHER_API_HOST=控制台分配的专属APIHost
QWEATHER_CREDENTIAL_ID=凭据ID
QWEATHER_DEVELOPER_ID=开发者ID
QWEATHER_PROJECT_ID=项目ID
QWEATHER_PRIVATE_KEY_BASE64=Ed25519私钥PEM的单行Base64
```

部署迁移 `0013_almanac_weather` 后，先用测试家庭搜索城市、启用天气，并验证小程序
预览、96,000 字节设备帧和下一次设备刷新。小程序保留“天气服务由和风天气驱动”
及服务网址；按产品要求，实体水墨屏底部不显示来源文字。正式对外提供设备前，应
再次确认供应商对无超链接特殊设备的署名或展示授权。

域名尚未解析时可以先构建后端，但暂时不要启动 Caddy。域名完成解析后，将
`API_DOMAIN` 设置为实际 API 子域名，再运行：

```bash
chmod +x deploy.sh backup.sh
./deploy.sh
curl --fail http://127.0.0.1:8000/health
docker compose ps
docker compose logs --tail=50 recognition-worker
```

Caddy 会在域名解析正确且公网 `80/443` 可访问后自动签发和续期 HTTPS 证书。

## OTA 私有固件目录

生产 compose 将 `/app/data/firmware-releases` 挂载为独立持久化卷，并通过
`firmware-storage-init` 设置后端进程的写权限。该目录只由带设备 HMAC 鉴权的
FastAPI 接口读取，Caddy 不直接暴露目录。生产 `.env` 保持：

```dotenv
OTA_FIRMWARE_STORAGE_DIR=/app/data/firmware-releases
OTA_MAX_SIGNED_BINARY_BYTES=3145728
```

部署 `0009_device_ota` 后，可先把本地已经签名的固件和公钥复制到容器临时目录，
再用导入工具验证并写入持久化卷；私钥不得上传服务器：

```bash
docker compose cp /安全路径/firmware-signed.bin \
  backend:/tmp/firmware-signed.bin
docker compose cp /安全路径/ota_public_key.pem \
  backend:/tmp/ota_public_key.pem
docker compose exec backend python -m tools.firmware_release import \
  --binary /tmp/firmware-signed.bin \
  --public-key /tmp/ota_public_key.pem \
  --version 1.0.1 --build 10001
docker compose exec backend rm -f \
  /tmp/firmware-signed.bin /tmp/ota_public_key.pem
```

导入后仍是 `draft`，不会触发任何设备升级。先按 `../../backend/README.md` 使用
`canary --device` 指定一台测试设备；禁止首次就设置 100%。数据库备份不包含固件
卷，因此每个签名发布包还必须在服务器之外保留一份只读归档。

## 备份

手动备份：

```bash
./backup.sh
```

脚本生成 PostgreSQL 自定义格式备份，只保留最近 14 天。正式上线后应再把备份
同步到服务器之外的对象存储，避免服务器磁盘故障时数据和备份一起丢失。
临时订单图片不属于备份内容，识别完成后立即删除，失败任务最迟 24 小时清理。
