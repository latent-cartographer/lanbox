# LanBox

LanBox 是一个只在内网使用的浏览器传递板。任意设备打开同一个局域网地址后，可以发送文本、链接、图片和文件；数据只保存在运行服务的这台机器上。

默认发出的内容是临时内容。所有打开 LanBox 的浏览器页面都关闭后，未保存内容和对应上传文件会自动删除；点过“保存”的内容会继续保留。

共享内容里的常见文件可以直接预览：图片、视频、音频、PDF 和较小的文本文件会显示“预览”按钮；其他文件继续通过文件名下载。

## 启动

```bash
python3 server.py
```

默认监听 `0.0.0.0:8787`。启动后终端会打印类似：

```text
LanBox running on http://127.0.0.1:8787
LAN address: http://<your-lan-ip>:8787
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
```

- `LANBOX_PORT`：端口，默认 `8787`
- `LANBOX_HOST`：监听地址，默认 `0.0.0.0`
- `LANBOX_MAX_UPLOAD_MB`：单次请求最大大小，默认 `1024`
- `LANBOX_CLIENT_TTL_SECONDS`：浏览器断开心跳后多久视为关闭，默认 `20`

## 数据位置

- 列表数据：`data/items.json`
- 上传文件：`data/uploads/`

未保存内容会被自动清理；已保存内容仍然保存在这些位置。

## 注意

这个工具默认没有账号和密码，适合可信内网。不要把端口暴露到公网。

## License

MIT
