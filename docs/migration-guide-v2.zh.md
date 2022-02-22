# 迁移指南 (至 v2)

## Docker / Docker Compose / 脏运行

1. **转到你的 bot。发送 `/export` 来备份你的订阅。**
1. (可选) 备份你的 `/path/to/bot/config/`。
1. 删除 `/path/to/bot/config/`。
1. 从头[重新部署](deployment-guide.md)你的 bot。按需配置[其他环境变量](advanced-settings.md)。
1. 转到你的 bot。发送 `/import` 来重新导入你的订阅。

## Railway.app

1. **转到你的 bot。发送 `/export` 来备份你的订阅。**
1. 转到你的 Railway 项目。
1. (可选) 备份你的 Redis 数据库，如果你知道怎么做的话。
1. 转到设置 (`Settings`) 页，切换到危险 (`Danger`) 标签。移除 (`Remove`) Redis 插件。
1. 点击左下角的添加插件 (`Add Plugin`) 按钮，选择添加 PostgreSQL (`Add PostgreSQL`)。
1. 转到变量 (`Variables`) 页。删除 (`Delete`) 环境变量 `CHATID` 和 `DELAY` 。按需配置[其他环境变量](advanced-settings.md)。
1. 转到你在 GitHub 上 fork 的仓库。切换到你已部署的分支，然后点击 `Fetch upstream` 和 `Fetch and merge`。
1. 等待你的 Railway 项目更新。
1. 转到你的 bot。发送 `/import` 来重新导入你的订阅。

## 如果你正在使用 `multiuser` 分支…

确保切换至 `master` 或 `dev` 分支。对于 Railway 来说，你可以通过切换部署触发器来做到这一点 (`Deployments` -> `Triggers` -> `Branches` -> 添加一个新的触发器并删除旧的)，**切记必须在开始根据本指南迁移之前完成这一步**。

## 如果你仍然希望限制 bot 仅为你服务…

请阅读 [FAQ](FAQ.md#q-我希望我的-bot-仅为我服务我应该怎么做)。
