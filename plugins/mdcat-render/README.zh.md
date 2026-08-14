# mdcat-render

通过 [mdcat](https://github.com/sharkdp/mdcat) CLI 把 Markdown 渲染成漂亮的终端输出——
CommonMark 加上 **bat 语法高亮**、**主题配色**、表格、mermaid 图、数学公式和 GFM 提示块。
JARVIS 自带的渲染器只是一个朴素的 ANSI 转换器;mdcat 是完整的 Rust 渲染器。

## 它是什么

一个 `kind="tool"` 插件,提供两个面:

1. **工具**——助手按需调用:
   - `md.render(text, theme?, ansi?)` — 渲染 markdown **文本**
   - `md.render_file(path, theme?, ansi?)` — 渲染 markdown **文件**
   默认会剥离 ANSI 转义(TUI / LLM 上下文里更安全);传 `ansi=true` 获得原始终端渲染。
2. **`render` 服务**——`channel-terminal` 的缓冲模式(`JARVIS_NO_STREAM=1`)
   在本插件加载时,回复会通过 `svc.render(text)` 渲染,替代内置的朴素渲染器。

## 配置

通过 config-core(`config.toml`):

```toml
[mdcat]
theme = "catppuccin-mocha"   # 可选:任意 mdcat/bat 主题名
```

单次调用的 `theme` 参数会覆盖配置值。

## 依赖

**需要 mdcat 二进制**(软依赖——绝不自动安装):

```bash
brew install mdcat          # macOS
cargo install mdcat         # 或从源码(Rust)
```

没有二进制时,工具会返回清晰的安装提示,`render` 服务回退为纯文本,一切照常。

## 安装

```bash
jarvis install https://github.com/<you>/mdcat-render.git
# 或者把这个目录放进 plugins/ 然后运行 jarvis bootstrap
```

## 安全说明

- `md.render_file` 可渲染任意路径——只读,不写入。
- mdcat 输出有上限(200 KB),子进程带 30 秒超时。
- 渲染不会执行 markdown 内容(mdcat 是渲染器,不是转换器)。

<!-- --- last modified by JARVIS <jarvis@jarvis.local> on 2026-08-15 03:33:28 --- -->
