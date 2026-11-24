# LoveLove · 生图工坊

一个跑在本地的图片生成网站。左侧输入提示词，右侧出图。后端代理到 YY AI 的 OpenAI 兼容接口，密钥只留在服务端。

## 结构

```
server.py        本地服务端（Python 标准库，零依赖）
web/index.html   单页前端（原生 JS，无构建步骤）
gen_image.py     命令行生图工具
gen-image.env    凭据文件（不入库，权限 600）
out/             生成结果（不入库）
```

## 开始使用

需要 Python 3.9+。

```bash
# 1. 配置凭据
cat > gen-image.env <<'EOF'
YYT_BASE_URL="https://yyt.im/v1"
YYT_API_KEY="sk-..."
YYT_ACTOR_HEADER="local-image-extension"
EOF
chmod 600 gen-image.env

# 2. 启动
./server.py                      # → http://127.0.0.1:8787
./server.py --port 9000          # 换端口
```

浏览器打开提示的地址即可。

## 命令行

```bash
./gen_image.py --list-models
./gen_image.py "黄昏的海边，胶片颗粒"
./gen_image.py "描述" -s 1024x1536 -o out/x.png
./gen_image.py "描述" -m "seedream-5.5（A）" -n 4
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面 |
| GET | `/api/models` | 可用模型（代理上游 `/models`，失败回退内置列表） |
| GET | `/api/recent` | 最近生成的图片 |
| POST | `/api/generate` | `{prompt, model, size, n}` → `{images, elapsed}` |
| GET | `/out/<name>.png` | 图片文件 |

尺寸限 `1024x1024`、`1024x1536`、`1536x1024`；`n` 限 1–4；提示词上限 2000 字。

## 已知特性

- 单张耗时 30–180 秒，服务端超时设 300 秒，`gen_image.py` 失败自动重试 2 次
- 请求头 `x-openai-actor-authorization` 必须带上，否则上游拒绝
- 上游返回 `b64_json` 或 `url` 两种格式，均已支持
- 前端有实时计时和骨架占位，避免长等待时以为卡死

## 密钥

`gen-image.env` 权限 600 且已列入 `.gitignore`。**不要提交**。换机器时只替换 `YYT_API_KEY` 一行。
