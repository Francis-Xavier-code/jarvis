# web-tools

面向助手的**网页搜索 + 抓取**工具 —— 补上"实时信息"这块最大短板。

- **kind**: `tool`
- **provides**:
  - `web.search(query, n?)` —— 搜索网页,返回 标题/URL/摘要 列表
  - `web.fetch(url, max_chars?)` —— 抓取页面并提取可读正文

## 后端

默认搜索后端为 **DuckDuckGo HTML 端点** —— 无需任何 API key。
可在 config.toml 配置自定义搜索 URL:

```toml
[web]
# 一个 GET 端点,返回含结果链接/摘要的 HTML
search_url = "https://html.duckduckgo.com/html/"
```

## 安全

* 只抓取 **http(s)** URL;15s 超时,200KB 读取上限。
* 两个工具都是只读(无需确认)——但抓取任意 URL 可能触达内网服务,请谨慎对待结果。

## 依赖

`requests`(软导入;`pip install requests` 安装)。
