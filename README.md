# TerraPanel

TerraPanel 是面向 Terraria tModLoader Dedicated Server 的 Web 管理面板。

## 当前能力

- 管理对象是 tModLoader Dedicated Server，不是原版 Terraria 或《饥荒联机版》服务器。
- 第一版面向 Linux x86_64。默认流程是在 Web 界面填写安装与世界配置，由面板下载官方 tModLoader Release、匹配的 .NET 运行时并完成一键开服。
- 支持安装任务状态与日志、取消、更新、已有实例关联、启动、停止、控制台、世界选择、`serverconfig.txt`、本地与 Workshop 模组发现、模组启用列表、日志、备份和恢复。
- Windows 进程执行、自动安装更新、多实例、定时任务和用户认证尚未实现。
- 所有路径和外部命令输入必须经过校验，文件与进程操作只能发生在已配置的服务器目录内。

## 技术方向

后端采用 Python 3.14、FastAPI 和 Pydantic，按 API、Service、Model/Repository 分层。应用入口负责集中装配依赖，业务服务显式接收依赖，不使用全局可变状态。

具体实现前必须核实目标 tModLoader Dedicated Server 版本的配置格式、启动参数和平台行为，不复用其他游戏服务器的领域模型。

当前目录边界：

```text
src/terrapanel/          应用入口、配置与领域代码
src/terrapanel/api/      HTTP 路由与请求响应模型
tests/                   单元测试和 API 测试
scripts/                 Linux 启动与维护脚本
```

## 实例目录

新实例会在 `storage.root_dir/servers` 内自动创建，实例目录名可在安装向导中修改。最终目录遵循 tModLoader DedicatedServerUtils 使用的结构：

```text
primary/
├── server/
│   ├── start-tModLoaderServer.sh
│   └── tModLoader.dll
├── Mods/
├── Worlds/
├── steamapps/workshop/
└── serverconfig.txt
```

`server/` 中的 tModLoader 与 .NET 由官方安装流程下载；`Mods/`、`Worlds/`、Workshop 目录、日志目录和 `serverconfig.txt` 由面板初始化。受管目录和文件不得是符号链接或目录联接。

## 本地运行

项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python、虚拟环境和依赖：

```powershell
# 安装锁定依赖
uv sync --frozen

# 创建本地配置并启动（PowerShell 可使用 Copy-Item）
cp config.example.yaml config.yaml
uv run terrapanel --config config.yaml
```

管理界面位于 `http://127.0.0.1:8080/`，健康检查地址为 `http://127.0.0.1:8080/api/v1/health`，OpenAPI 页面位于 `http://127.0.0.1:8080/docs`。

也可以通过 Shell 脚本启动：

```bash
sh scripts/start.sh --config config.yaml
```

首次打开管理界面后，在“新建服务器”中填写实例、世界和端口配置并执行“安装并开服”。默认安装最新稳定版，也可以填写 `v2024.6.3.1` 形式的版本标签。等价 API：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/provisioning \
  -H 'Content-Type: application/json' \
  -d '{"name":"Primary Server","root_dir":"primary","world_name":"TerraPanel","world_size":1,"difficulty":1,"max_players":8,"port":7777,"password":"","motd":"","secure":true,"upnp":false,"start_after_install":true}'
```

自动安装需要宿主机提供 `bash`、`curl`、`tar` 和 `unzip`。Docker 镜像已经包含这些系统工具及 SteamCMD 所需的 32 位运行库；Linux 裸机启动时若缺少工具，任务日志会列出缺失项。面板不会从 Web 进程提权执行 `apt`、`dnf` 等系统包管理器。

裸机运行时只需修改一个根目录，面板状态、服务端、世界、模组、Workshop、日志和备份都会随之移动：

```yaml
storage:
  root_dir: /srv/terrapanel
```

环境变量使用 `TERRAPANEL_` 前缀和双下划线表示嵌套字段，例如 `TERRAPANEL_HTTP__PORT=8081`、`TERRAPANEL_STORAGE__ROOT_DIR=/srv/terrapanel`。旧的 `data_dir`、`servers_dir` 和 `backups_dir` 仍可用于分别覆盖目录。`.tmod` 上传上限默认是 256 MiB，可通过 `TERRAPANEL_MODS__MAX_UPLOAD_SIZE` 按字节覆盖；世界存档上传总上限默认是 512 MiB，可通过 `TERRAPANEL_WORLDS__MAX_UPLOAD_SIZE` 调整。

## API

所有业务接口位于 `/api/v1`：

| 功能 | 接口 |
|------|------|
| 健康检查 | `GET /api/v1/health` |
| 安装与更新 | `GET/POST /provisioning`、`POST /provisioning/update`、`POST /provisioning/cancel`、`GET /provisioning/logs` |
| 实例关联与移除 | `GET/PUT/DELETE /instance` |
| 生命周期 | `POST /instance/start`、`POST /instance/stop`、`GET /instance/status` |
| 控制台 | `GET/POST /instance/console` |
| 服务配置 | `GET/PATCH /server-config` |
| 世界存档 | `GET /worlds`、`POST /worlds/upload`、`POST /worlds/select`、`DELETE /worlds/{name}` |
| 模组 | `GET /mods`、`POST /mods/upload`、`POST /mods/enable`、`POST /mods/disable`、`DELETE /mods/local/{name}` |
| 日志 | `GET /logs/{console\|server\|launch\|native}` |
| 备份 | `GET/POST /backups`、`GET /backups/{id}/download`、`POST /backups/{id}/restore`、`DELETE /backups/{id}` |

完整请求模型和响应模型见运行中的 `/docs`。

服务端停止后，可以在模组页直接上传 `.tmod`，也可以使用 API。上传会校验包头、声明长度和 SHA-1，按包内模组名保存，且不会自动启用；同名更新需要显式允许覆盖：

```bash
curl -F 'file=@ExampleMod.tmod' http://127.0.0.1:8080/api/v1/mods/upload
curl -F 'file=@ExampleMod.tmod' 'http://127.0.0.1:8080/api/v1/mods/upload?replace=true'
curl -X DELETE http://127.0.0.1:8080/api/v1/mods/local/ExampleMod
```

删除接口只处理本地上传的 `.tmod`，并同步清理 `enabled.json`；Workshop 模组仍由其订阅和更新流程管理。

“存档”页面支持导入一个 `.wld` 和可选的同名 `.twld`、切换当前世界及删除非当前世界。导入不会自动切换当前世界；覆盖导入会把 `.wld/.twld` 作为一组替换。删除会清理同名主文件和直接 `.bak` 伴随文件，但保留 `Worlds/Backups` 中的历史 ZIP：

```bash
curl -F 'files=@Example.wld' -F 'files=@Example.twld' \
  http://127.0.0.1:8080/api/v1/worlds/upload
curl -X POST -H 'Content-Type: application/json' \
  -d '{"path":"Worlds/Example.wld"}' \
  http://127.0.0.1:8080/api/v1/worlds/select
```

## Docker

从 GitHub Container Registry 拉取最新的 Linux x86_64 镜像并启动：

```bash
docker compose pull
docker compose up -d --no-build
```

也可以固定到版本标签，避免后续自动切换版本：

```bash
TERRAPANEL_IMAGE=ghcr.io/lumidust/terrapanel:0.1.0 docker compose up -d --no-build
```

本地修改源码后需要自行构建时，覆盖镜像名并启用构建：

```bash
TERRAPANEL_IMAGE=terrapanel:dev docker compose up -d --build
```

使用离线镜像归档时，先校验并加载镜像，再通过 Compose 启动：

```bash
sha256sum --check terrapanel-0.1.0-linux-amd64.tar.sha256
docker load --input terrapanel-0.1.0-linux-amd64.tar
TERRAPANEL_IMAGE=terrapanel:0.1.0 docker compose up -d --no-build
```

仓库中的 GitHub Actions 会自动构建并发布 `linux/amd64` 镜像到 GHCR：

| Git 事件 | 发布标签 |
|----------|----------|
| 推送到 `main` | `latest`、`sha-<短提交号>` |
| 推送 `v0.1.0` 形式的版本标签 | `0.1.0`、`0.1`、`0`、`sha-<短提交号>` |
| 手动运行工作流 | 当前分支对应的 SHA 标签；`main` 同时更新 `latest` |

首次发布后，仓库所有者需要在 GitHub Packages 中把容器包可见性设为 Public，公开用户才能免登录拉取。包保持私有时，需要先使用具有 `read:packages` 权限的令牌执行 `docker login ghcr.io`。

容器默认只在宿主机 `127.0.0.1:8080` 发布面板端口，并把宿主机 Terraria `7777` 映射到容器 `7777`；运行数据和自动安装的服务器保存在 `terrapanel-data` 数据卷。`TERRAPANEL_GAME_PORT` 控制宿主机端口，`TERRAPANEL_SERVER_PORT` 必须与安装向导中的服务器端口一致，两者默认都是 `7777`。

所有持久化文件都集中在独立容器目录 `/data`，不写入 `/var`。其中 `<实例目录>` 默认为 `primary`：

| 数据 | 容器路径 |
|------|----------|
| 面板状态 | `/data/instance.json`、`/data/provisioning.json` |
| 服务端实例 | `/data/servers/<实例目录>/server` |
| 世界存档 | `/data/servers/<实例目录>/Worlds` |
| 本地模组与启用列表 | `/data/servers/<实例目录>/Mods` |
| Workshop 内容 | `/data/servers/<实例目录>/steamapps` |
| 日志 | `/data/servers/<实例目录>/logs` |
| 备份 | `/data/backups` |

设置 `TERRAPANEL_DATA_PATH` 可以把整个固定布局绑定到宿主目录 `/data`：

```bash
mkdir -p ./terrapanel-data
sudo chown -R 10001:10001 ./terrapanel-data
TERRAPANEL_DATA_PATH=./terrapanel-data docker compose up -d --build
```

容器以 `10001:10001` 运行，宿主目录必须允许该用户读写。未设置 `TERRAPANEL_DATA_PATH` 时继续使用原有 `terrapanel-data` 命名卷；旧版本卷中的文件结构不变，只是容器内挂载点从 `/var/lib/terrapanel` 调整为 `/data`。

第一版没有内置认证。不要直接发布到公网；远程使用时应放在带 TLS 和认证的反向代理或受控 VPN 后面。

## 前端开发

后端运行在 `8080` 时，可启动带 API 代理的 Vite 开发服务器：

```bash
cd frontend
npm ci
npm run dev
```

生产静态资源由 `npm run build` 输出到 `src/terrapanel/static/`，随后随 Python wheel 一同打包。

## 质量检查

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv lock --check

cd frontend
npm ci
npm run build
npm run typecheck
npm exec playwright test
```
