# LanBox

LanBox 是一个只在内网使用的浏览器传递板。任意设备打开同一个局域网地址并输入访问口令后，可以发送文本、链接、图片和文件；数据只保存在运行服务的这台机器上。

默认发出的内容是临时内容。所有打开 LanBox 的浏览器页面都关闭后，未钉住内容和对应上传文件会自动删除；也可以给单条内容设置过期时间。点过“钉住”的内容会继续保留，取消钉住后会重新参与自动清理。

共享内容里的常见文件可以直接预览：图片、视频、音频、PDF 和较小的文本文件会显示“预览”按钮；一条内容里的多个文件可以打包为 ZIP 下载。

页面带有 PWA manifest，可以添加到主屏幕；完整 PWA 安装能力取决于浏览器和访问方式，移动端 HTTP 局域网地址可能只能作为普通主屏幕快捷方式。

## 启动

```bash
python3 server.py
```

也可以使用启动脚本：

```bash
./scripts/start.sh
```

固定访问口令启动：

```bash
LANBOX_ACCESS_CODE=123456 ./scripts/start.sh
```

默认监听 `0.0.0.0`，端口可通过 `LANBOX_PORT` 配置。启动后终端会打印类似：

```text
LanBox running on http://127.0.0.1:<port>
LAN address: http://<your-lan-ip>:<port>
Access code: 123456
```

其他设备连接同一个 Wi-Fi 或局域网后，打开 `LAN address` 里的地址即可。页面左侧有“扫码进入”按钮，点击后会显示二维码，后续手机、平板或其他人的设备可以直接扫电脑屏幕进入。

如果仍然想在终端里打印二维码，可以这样启动：

```bash
LANBOX_TERMINAL_QR=1 python3 server.py
```

## 配置

```bash
LANBOX_PORT=9000 python3 server.py
LANBOX_MAX_UPLOAD_MB=2048 python3 server.py
LANBOX_CLIENT_TTL_SECONDS=20 python3 server.py
LANBOX_BACKGROUND_CLIENT_TTL_SECONDS=600 python3 server.py
LANBOX_ACCESS_CODE=123456 python3 server.py
LANBOX_ACCESS_CODE=off python3 server.py
```

- `LANBOX_PORT`：端口，默认 `8787`
- `LANBOX_HOST`：监听地址，默认 `0.0.0.0`
- `LANBOX_MAX_UPLOAD_MB`：单次请求最大大小，默认 `1024`
- `LANBOX_CLIENT_TTL_SECONDS`：前台页面断开心跳后多久视为关闭，默认 `20`
- `LANBOX_BACKGROUND_CLIENT_TTL_SECONDS`：后台页面断开心跳后多久视为关闭，默认 `600`
- `LANBOX_ACCESS_CODE`：访问口令，默认启动时自动生成；设为 `off` 可关闭口令

## 数据位置

- 列表数据：`data/items.json`
- 上传文件：`data/uploads/`

未钉住内容会被自动清理；已钉住内容仍然保存在这些位置。

## 注意

这个工具只有轻量访问口令，没有账号系统，适合可信内网。不要把端口暴露到公网。

## License

MIT
