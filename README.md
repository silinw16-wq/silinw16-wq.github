# Skill Bowl V0.1

私有 Markdown Skill 托管与远程调用服务。Python 3.12+，使用 FastAPI；Skill 文件与核心服务分离。无网页、数据库、分类、支付、多租户或 Python Skill 执行功能。原有 index.html 是旧仓库文件，与本服务无关。

## 项目结构

```text
skill_bowl/
  core.py                 # 配置、manifest 校验、Skill 发现
  app.py                  # HTTP API、鉴权、模型调用
examples/skills/
  writer/{SKILL.md,manifest.json}
  reviewer/{SKILL.md,manifest.json}
tests/test_service.py
requirements.txt
.env.example
.gitignore
```

examples 仅含可公开的演示指令。真实私有 Skill 放在仓库外，或被忽略的根目录 skills/；不得放入 examples 或其他被跟踪目录。`.env` 和私有 Skill 不得提交。服务不会托管任何静态文件。

## 本地启动

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
# 首次演示：将公开示例复制到被忽略的私有目录；已有 skills 时不要覆盖。
cp -R examples/skills ./skills
export SKILL_BOWL_SKILLS_DIR="$PWD/skills"
export SKILL_BOWL_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m uvicorn skill_bowl.app:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log
```

无模型配置时可查询列表和健康状态，执行返回 503。`.env.example` 只提供变量说明；服务不自动读取 `.env`。密钥请在本机安全的 shell/进程环境配置，不要提交或发到聊天中。

```sh
export MODEL_API_URL='https://供应商域名/v1/chat/completions'
export MODEL_NAME='模型名称'
# 避免将真实密钥写入 shell 历史；下面在 Bash 中交互读取：
read -rs -p 'Model API key: ' MODEL_API_KEY; echo
export MODEL_API_KEY
export MODEL_TIMEOUT_SECONDS=30
```

配置后重启服务。接口适配 OpenAI Chat Completions 格式（非流式），URL 为完整 HTTPS endpoint；不会跟随重定向。需要供应商支持 system/user messages 及 choices[0].message.content 返回格式。真实调用可能计费，须由操作者确认后再执行。仓库测试全部使用模拟响应，不访问模型供应商。

## Skill 格式与扩展

每个直接子文件夹必须有 UTF-8 `SKILL.md` 和 `manifest.json`：

```json
{"id":"writer","name":"写作助手","description":"公开简介","type":"markdown","enabled":true}
```

字段必须完整且无额外字段，id 必须唯一且符合 `[a-z][a-z0-9_-]{0,63}`。SKILL.md 非空且不超过 64 KiB，manifest 不超过 8 KiB，不允许符号链接。仅加载 enabled=true 的 Skill。停用的文件也必须有效；任何无效 Skill 使启动失败，避免悄悄漏加载。添加文件夹或修改 enabled 后重启即可生效，无需修改核心代码。Skill 在启动时读取为内存快照；没有热更新或管理上传接口。不会执行脚本或模板代码。

## API

`GET /health` 无需认证。其余接口使用 `Authorization: Bearer $SKILL_BOWL_API_TOKEN`，这是服务访问令牌，与供应商密钥不同。

- `GET /v1/skills`：返回启用 Skill 的 id/name/description，不返回指令。
- `POST /v1/execute`：统一执行接口，返回 `{"skill_id":"writer","result":"..."}`。

请求体示例：

```json
{"skill_id":"writer","input":"写一段活动介绍","feedback":"更简洁","previous_result":"上一版文案"}
```

input 必填，最多 8000 字符；feedback 最多 4000 字符；previous_result 最多 16000 字符；整个请求体最多 64 KiB，未知字段拒绝。修改场景须同时自行传入需要的上一版和意见；服务不保存会话。用户数据以 JSON 放入 user message，私有 Skill 放入 system message。输出最多 32000 字符，上游响应最多 256 KiB。最多 8 个并行模型调用，总超时包括排队；默认 30 秒，最大 120 秒。

常见状态：401 未认证；404 未启用或不存在；413 请求体过大；422 参数错误；502 上游失败/响应无效；503 缺少模型配置；504 超时。错误不回传上游原文、密钥、提示词或验证输入。日志仅记录服务生成的请求 ID 和响应状态；部署时保持 `--no-access-log`，避免 URL 查询参数进入访问日志。

## 安全边界

服务不提供 Skill 下载、源码、交互文档或静态目录。配置强制访问令牌至少 24 字符；默认仅绑定回环地址。远程部署必须在可信 HTTPS 反向代理后运行，设置连接/请求读取超时、限流和访问控制；不要把开发端口直接暴露到公网。V0.1 没有跨进程限流、队列长度控制或用户隔离。

模型供应商会收到完整 Skill 和用户内容，必须自行选择可信供应商并审查数据政策。本服务不写入这些内容到日志或数据库。模型有提示词提取风险：system 保密指令及完整指令原文回显拦截只能降低风险，无法保证阻止片段、改写或编码泄露；不要把密钥或其他秘密放在 Skill 指令中。公开简介应手工审查。服务配置和 Skill 目录只应由可信管理员维护。

发布前运行 `git status --short` 与 `git check-ignore .env skills/`，确认私有目录及环境文件未被跟踪。`.gitignore` 不会保护已经被跟踪的文件；如果真实密钥曾提交，必须撤销并轮换。

## 验证

```sh
python3 -m unittest discover -s tests -v
```

测试覆盖两种 Skill、添加第三种、停用重启、鉴权、输入上限、无效清单/链接/重复 ID、模拟模型切换及修订、超时、上游异常、日志脱敏、指令原文回显拦截。未运行真实模型测试。手工检查 `/health` 与带认证的 `/v1/skills` 后，只有在确认供应商及费用后才请求 `/v1/execute`。不需要部署 GitHub Pages。

## 工作包②：MCP 与 Token 授权

新增 `skill_bowl/mcp_app.py`，复用已有 REST 应用的 Skill 加载、执行、校验及上游调用，不修改工作包①核心代码。新增依赖官方 `mcp==1.29.0`；安装命令仍为 `python3 -m pip install -r requirements.txt`。

MCP 使用独立进程入口（不会将原有 REST API 自动暴露到 MCP 端口）：

```sh
# 保留前述 SKILL_BOWL_SKILLS_DIR、REST Token 和可选模型配置。
export SKILL_BOWL_MCP_RUN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SKILL_BOWL_MCP_READ_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m uvicorn skill_bowl.mcp_app:create_app --factory --host 127.0.0.1 --port 8002 --no-access-log
```

端点路径 `/mcp`，传输为 stateless Streamable HTTP，使用 JSON responses；不是旧版 HTTP+SSE。客户端每次请求均须发送 `Authorization: Bearer <MCP Token>`。RUN 必填，READ 可省略；Token 至少 24 字符且必须互不相同，也不得复用 REST Token。不要把 Token 放 URL 中。

| 工具 | 参数 | 权限 |
| --- | --- | --- |
| `list_skills` | 无 | READ 或 RUN |
| `run_skill` | `skill_id`、`input`；可选 `feedback`、`previous_result` | RUN |

工具返回公开 Skill 信息或执行结果；不注册私有资源、提示词模板、文件下载或密钥读取工具。无权请求返回 HTTP 401；工具权限、参数或业务错误返回 MCP `isError=true` 和通用脱敏消息。读取 Token 不能触发模型，REST Token 不能访问 MCP；不是多租户隔离。

沿用工作包①字段限制及模型超时；MCP 请求体上限 64 KiB，请求总时限为模型配置超时加 5 秒。日志只保留随机请求 ID、HTTP 状态及通用事件，SDK 协议日志也作脱敏。SDK 版本固定，升级后需复查日志行为。部分错误（如只读 Token 调用执行工具）使用 MCP 工具错误，HTTP 仍可能为 200，应检查 `isError`。

默认启用 Host/Origin 校验，仅允许本机 Host；远程部署需设置 `SKILL_BOWL_MCP_ALLOWED_HOSTS` 为明确的可信主机及端口，浏览器场景还需明确设置 `SKILL_BOWL_MCP_ALLOWED_ORIGINS`（逗号分隔，默认不允许带 Origin 的请求）。保留 HTTPS 反向代理、请求读取超时和限流要求。该版本不提供 OAuth、用户管理、Token 管理后台或公开部署。

[WorkBuddy 兼容性与来源记录](docs/workbuddy-compatibility.md)：官方资料入口访问被网络策略拒绝，WorkBuddy 的传输协议和认证字段仍待核实。当前只确认本服务与所用官方 Python SDK 协议互通，未开发或测试 WorkBuddy 实际远程连接。

运行 `python3 -m unittest discover -s tests -v` 将同时运行原业务单元测试和 `tests/test_mcp.py` 中的真实本地 HTTP MCP 协议测试（需要本地监听端口权限，端口自动选择并在结束时关闭）。上游模型全部模拟，不会访问供应商。测试输出可能包含已安装依赖的弃用/类型注解警告，不影响本轮执行结果。

## 工作包③：Windows / Cursor 本地准备

在 Windows 项目根目录执行 ` .\scripts\start-skill-bowl.ps1`（或 `py -3 .\scripts\start_local.py`），自动创建虚拟环境、准备私有本地 Skill 和 Token，生成被 Git 忽略的 `.cursor/mcp.json` 并启动回环地址 MCP 服务。不会调用模型。

[最短连接步骤、模型配置及验收清单](docs/cursor-local-acceptance.md)。Cursor 官方文档本轮访问被网络策略拒绝，生成的配置是待本机核实方案；Windows 启动、Cursor UI 和真实模型端到端测试均未执行，不宣称工作包③完整验收通过。用户选择稍后在本地验证。

`python -m skill_bowl.check_mcp` 默认只做本地协议、Token 和列表检查，不触发模型。真实执行模式必须显式确认，详见上述文档。新增输出保护会拒绝 MCP 响应中已知 Token、模型密钥或已加载 Skill 完整原文的直接回显；它无法保证防止所有改写和编码形式的提示词泄露。
