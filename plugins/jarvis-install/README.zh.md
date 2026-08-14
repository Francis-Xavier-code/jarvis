# jarvis-install

内核的拉取能力,被暴露**为插件** —— 因为"安装一个插件"本身也是一种能力,所以它
和其它一切一样,活在插件系统里。

> English docs: [README.md](README.md)

- **kind**: `tool`
- **provides** 两个工具:

```
jarvis.install_plugin(git_url: str, name: str = "") -> str
    克隆一个遵循 JARVIS plugin.toml 约定的 git 仓库到 plugins/<name>/ 并热加载。
    返回插件名。
    示例:一个 jarvis-homeassistant 仓库会立刻变成可用的 hass.* 工具。

jarvis.uninstall_plugin(name: str) -> str
    按名字卸载一个已加载的插件(teardown + 注销)。
```

## 等价的入口

| 想要…… | 使用 |
|---------|------|
| 在对话中安装 | `jarvis.install_plugin` 工具 |
| 在命令行安装 | `jarvis install <git_url>` |
| 启动时安装默认包 | 在 `plugin-sources.toml` 中登记,然后 `jarvis bootstrap` |

这三种方式调用的都是同一个 `Kernel.install_plugin` 路径。

## 安全

本工具会克隆并执行任意 git 仓库。**只安装你信任的来源** —— 一个恶意插件会拥有与
JARVIS 相同的权限。
