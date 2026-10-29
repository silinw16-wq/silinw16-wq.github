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
