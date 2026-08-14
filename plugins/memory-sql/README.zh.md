# memory-sql

JARVIS 的 SQLite 记忆后端:按会话的对话历史 + 跨会话事实,全部存在一个数据库文件
(`<data_dir>/memory/memory.db`)里,替代 JSONL 文件。

## 它是什么

一个 `kind="memory"` 插件,与 `memory-jsonl` 接口完全一致(load / append /
save + 事实存取),同样提供 `mem.store` / `mem.recall` / `mem.forget` 工具,
另外多两个:

- `mem.status` — 当前后端、数据库路径、存量统计、迁移统计
- `mem.migrate` — 重新扫描旧 JSONL 位置,导入任何新数据

**后端接管**:服务与工具都是后注册者胜出,且插件按目录名排序加载——
`memory-sql` 排在 `memory-jsonl` 之后,所以会自动成为生效的记忆后端。
删除(或改名)jsonl 插件即可彻底停用 JSONL 后端。

## 旧 JSONL 迁移

启动时(以及通过 `mem.migrate` 手动触发)会按顺序扫描以下候选位置,
把 memory-jsonl 的数据导入 SQLite:

1. `<data_dir>` — 数据库所在目录
2. `$JARVIS_DATA` — 设置了且不同时
3. 当前工作目录 — 旧版 memory-jsonl 曾把数据写在这里

导入**按行幂等**:新会话整体导入;已存在的会话会把 JSONL 里缺失的旧行**合并到
最前面**(保证对话顺序正确);事实仅在不存在时插入。重复执行只会补新数据,绝不产生重复。

## 配置

无需配置。数据库路径跟随 `kernel.data_dir`(默认 `~/Library/Application Support/jarvis/memory/memory.db`)。

## 依赖

无(仅标准库 `sqlite3`)。WAL 模式 + 线程锁,对内核的 worker 线程和热重载安全。

## 安装

```bash
jarvis install https://github.com/<you>/memory-sql.git
# 或者把目录放进 plugins/ 后运行 jarvis bootstrap
# (必须排在 memory-jsonl 之后才能接管——"memory-sql" 满足)
```

## 安全说明

- SQL 全部参数化(会话名是数据,不是 SQL)。
- 会话名原样存储(不据此生成文件路径,无路径穿越风险)。
- 迁移后**不删除**旧 JSONL 文件——什么都不会丢。

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 04:03:00 --- -->
