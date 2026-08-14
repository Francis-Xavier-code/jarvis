# agent-tools

给助手真正的 **bash + 文件系统** 工具(pi-agent 风格),让它在你的机器上**动手做事**,
而不只是嘴上说说。

- **kind**: `tool`
- **provides**:
  - `bash.execute` —— 执行 shell 命令(每次都需要用户确认)
  - `fs.read` —— 读取 UTF-8 文本文件
  - `fs.write` / `fs.edit` / `fs.append` —— 修改文件(先自动备份)
  - `fs.list` / `fs.glob` —— 发现文件
  - `fs.undo` —— 从最近一次自动备份恢复文件

## 安全模型

* **每次 `bash.execute` 都要用户明确确认**(交互式 y/N 提示;可通过
  `kernel.confirm_action` 替换)。
* **项目根目录内**(包括 JARVIS 插件):直接可改 —— 内核热重载编辑,且**加载失败会回滚**
  到之前的注册表,改坏也不会让能力消失。
* **项目根目录外**:需要用户确认。
* **直接拒绝**:`config.toml`(含密钥)读和写都拒;`.git/`、`.venv/`、`data/`、
  `sessions/`、`backups/` 拒绝写入。

## 回退保底(自我修复闭环)

每次 write/edit/append 都会把原文件快照到 `<data_dir>/backups/`(保留最近 5 份)。
如果助手把文件改坏了:

1. 插件热重载失败,**旧工具仍然在线**(自动回滚);
2. 让助手调用 `fs.undo(path)`(或手动修好文件);
3. 下一次热重载检查就会加载修复后的文件 —— 无需重启,能力不丢。
