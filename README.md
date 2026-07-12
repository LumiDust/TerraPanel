# TerraPanel

TerraPanel 是一个面向 Terraria tModLoader 专用服务器的 Web 管理面板。你可以在浏览器中完成服务器安装、启动、配置、模组管理、存档切换、备份恢复和日志查看，不需要反复手动执行 tModLoader 命令。

## 主要功能

- 自动下载 tModLoader 和运行依赖，配置完成后可以一键开服
- 启动、停止和查看服务器状态
- 在浏览器中使用服务端控制台
- 修改端口、玩家上限、密码和欢迎信息
- 上传、启用、停用和删除本地 `.tmod` 模组
- 查看已安装的 Workshop 模组
- 上传、切换和删除世界存档
- 创建、下载、恢复和删除备份
- 查看并筛选服务端日志

## 适用范围

当前版本面向 Linux x86_64，优先推荐使用 Docker。它管理的是 tModLoader Dedicated Server，不是原版 Terraria 服务器。

目前以单个服务器实例为主，尚未提供多实例、定时任务和用户登录功能。Windows 裸机运行也不在当前支持范围内。

## Docker 快速开始

服务器需要安装 Docker 和 Docker Compose，并能访问 GitHub 与 Steam 下载服务。

```bash
git clone https://github.com/LumiDust/TerraPanel.git
cd TerraPanel
mkdir -p data
sudo chown -R 10001:10001 data
docker compose pull
docker compose up -d --no-build
```

启动后，在服务器本机打开：

```text
http://127.0.0.1:8080
```

面板默认只监听宿主机本地地址。远程管理时可以使用 SSH 隧道：

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

然后在自己电脑的浏览器中打开 `http://127.0.0.1:8080`。

## 第一次开服

1. 打开面板，在安装页面填写服务器名称、世界名称、难度、玩家上限和端口。
2. tModLoader 版本留空时会使用当前稳定版；需要固定版本时再填写对应版本号。
3. 点击“安装并开服”，等待安装日志完成。
4. 状态变为“运行中”后，玩家可以通过服务器地址和游戏端口加入。

首次安装需要下载 tModLoader、.NET 运行时和 Steam 相关内容，耗时取决于服务器网络。不要在安装过程中关闭容器或删除数据目录。

## 数据保存

默认情况下，所有服务器数据都通过 bind mount 保存在项目根目录的 `./data` 中。这个目录可以直接查看、复制和备份，更新或重建容器不会删除其中的内容。

Linux 上首次启动前需要创建目录，并让容器用户拥有写入权限：

```bash
mkdir -p data
sudo chown -R 10001:10001 data
```

主要数据都位于这个目录下：

| 内容 | 相对位置 |
|------|----------|
| 服务端文件 | `servers/<实例目录>/server` |
| 世界存档 | `servers/<实例目录>/Worlds` |
| 本地模组 | `servers/<实例目录>/Mods` |
| Workshop 内容 | `servers/<实例目录>/steamapps` |
| 服务端日志 | `servers/<实例目录>/logs` |
| 面板备份 | `backups` |

需要把数据放到其他位置时，直接修改 `compose.yaml` 中 `volumes` 的左侧路径，并提前创建目标目录、授予 UID/GID `10001:10001` 写入权限。

从使用命名卷的旧版本升级时，旧数据不会自动出现在 `./data`。升级前应停止服务器并备份或迁移旧卷；确认新目录中的世界、模组和备份完整后，再处理旧卷。

## 端口和常用设置

镜像、端口映射和数据目录都直接写在 `compose.yaml` 中：

```yaml
services:
  terrapanel:
    image: "ghcr.io/lumidust/terrapanel:latest"
    ports:
      - "127.0.0.1:8080:8080"
      - "7777:7777"
    volumes:
      - "./data:/data"
```

- 面板映射 `127.0.0.1:8080:8080` 中，中间的 `8080` 是宿主机端口，最后的 `8080` 是容器端口。
- 游戏映射 `7777:7777` 中，左侧是玩家连接的宿主机端口，右侧是容器端口，并且必须与面板中的服务器端口一致。
- 数据映射 `./data:/data` 中，左侧是宿主机目录，右侧是容器内固定目录，不应修改右侧 `/data`。
- `image` 后的标签决定使用的 TerraPanel 版本。

修改 `compose.yaml` 后重新执行：

```bash
docker compose up -d --no-build
```

如果玩家无法加入，请确认游戏端口已经在主机防火墙和云服务商安全组中放行。

## 日常管理

### 模组

修改模组前先停止服务端。在“模组”页面上传 `.tmod` 文件，然后启用需要的模组并重新开服。同名模组需要确认覆盖；删除本地模组时会同步从启用列表中移除。

Workshop 模组会显示在列表中，但其下载和更新仍由 Workshop 配置与 Steam 流程负责。

### 世界存档

“存档”页面可以上传 `.wld`，以及可选的同名 `.twld` 文件。上传后再选择它作为当前世界；正在使用的世界不能直接删除。

切换、覆盖或删除存档前应停止服务端并创建备份。

### 备份

在更新 tModLoader、替换模组或切换世界前创建备份。重要备份建议下载到其他设备，避免只保存在同一块磁盘上。

恢复备份会替换当前服务器内容，操作前必须停止服务端。

### 控制台和日志

“控制台”页面用于发送服务端命令并查看实时输出。“日志”页面用于检查启动失败、模组加载错误和运行异常。

## 更新 TerraPanel

1. 在面板中创建备份。
2. 停止 tModLoader 服务端。
3. 拉取新镜像并重建面板容器。

```bash
docker compose pull
docker compose up -d --no-build
```

数据目录不会因容器更新而删除。需要固定版本时，直接修改 `compose.yaml` 中的镜像标签：

```yaml
image: "ghcr.io/lumidust/terrapanel:<版本号>"
```

可用版本以 GitHub Packages 中实际发布的标签为准。

## 不使用 Docker

Linux 裸机需要 Python 3.14、uv、bash、curl、tar、unzip，以及 SteamCMD 所需的 32 位运行库。缺少系统依赖时建议改用 Docker。

```bash
git clone https://github.com/LumiDust/TerraPanel.git
cd TerraPanel
uv sync --frozen
cp config.example.yaml config.yaml
sh scripts/start.sh --config config.yaml
```

启动前请在 `config.yaml` 中把 `storage.root_dir` 改成用于长期保存服务器数据的目录。

## 安全提醒

当前版本没有内置账号和登录验证，不要直接把面板端口暴露到公网。远程管理建议使用以下任一方式：

- SSH 隧道
- 带 TLS 和身份验证的反向代理
- 受控 VPN 或内网

游戏端口可以按需对玩家开放，面板端口应保持受保护状态。

## 常见问题

### 镜像无法拉取

如果出现 `denied` 或 `unauthorized`，请确认 GHCR 容器包已经设为 Public；私有包需要先登录 `ghcr.io`。

### 数据目录没有写入权限

Docker 容器使用 UID/GID `10001:10001`。绑定宿主目录时，需要让该用户能够读写目录。

### 安装一直失败

先检查服务器是否能访问 GitHub 和 Steam，再到面板的安装日志中查看具体失败步骤。网络中断后可以重新发起安装或更新。

### 容器是否正常运行

```bash
docker compose ps
docker compose logs --tail=200 terrapanel
```

面板健康时，`docker compose ps` 会显示容器为 `healthy`。
