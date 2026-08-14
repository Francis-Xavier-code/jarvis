# provider-openai

JARVIS 真正的 **LLM 大脑**。它使用 OpenAI Chat Completions API,因此能对接**任何**
OpenAI 兼容端点 —— 而"模型厂商聚合商"正是一种 OpenAI 兼容端点。默认配置的厂商是
**opencodego**(一个 API key → 多家底层厂商:minimax / kimi / glm / deepseek / qwen
/ ……),但改一下 base URL,同一个插件就能指向 OpenAI、本地 llama.cpp 等。

> 中文文档: [README.zh.md](README.zh.md)

- **kind**: `provider`
- **provides**: 自身不提供工具 —— 它是模型

## 配置

通过 `config-core` 插件(`config.toml`)**或**环境变量读取:

| config.toml 键 | 环境变量 | 默认值 | 含义 |
|----------------|----------|--------|------|
| `openai_base_url` | `OPENAI_BASE_URL` | `https://opencode.ai/zen/go/v1` | API 地址 |
| `openai_api_key` | `OPENAI_API_KEY` | — | API key(**密钥**) |
| `model` | `MODEL` | `kimi-k3` | 默认请求的模型 |

> **安全**:绝不要提交 API key。把它放进 `config.toml`(已被 gitignore,见 `.gitignore`
> 的 `config.toml` 规则),或更好的做法是在 shell / 永不提交的 `.env` 里 `export
> OPENAI_API_KEY`。

## 工具调用

其他插件提供的工具规格(ToolSpec)会被作为 OpenAI `tools` 转发给模型。当模型发出函数
调用时,本插件 yield 一个 `ChatChunk(tool_call=...)`,内核路由它、把结果回灌并重复
(最多 4 轮)。工具结果会在插件内部重新绑定到对应的 `tool_call_id`(内核不替我们记录
这个 id)。

## 依赖

使用 `requests`(软导入)。安装一次:

```
uv pip install requests
```
