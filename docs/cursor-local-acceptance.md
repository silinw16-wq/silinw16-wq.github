# 工作包③：Cursor 本地接入与验收准备

日期：2026-10-29。用户选择本轮仅完成准备，稍后本地验证。没有调用真实模型、购买资源或操作 Cursor。

## 官方资料调查与结论

尝试读取 Cursor 官方文档目标地址：

- https://cursor.com/docs/context/mcp
- https://docs.cursor.com/context/model-context-protocol

两个地址均被当前网络代理返回 HTTP 403，未取得正文，无法核实当前 Cursor 版本的传输支持、配置字段及认证要求，也无法确认这些路径当前是否仍有效。本环境没有 Cursor 或 Windows PowerShell。不能据此宣称 Cursor 兼容或真实连接已成功。

已验证的服务端协议依据仍是 [官方 Python MCP SDK v1.29.0](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/README.md)，详见 [工作包②调查](workbuddy-compatibility.md)。当前服务提供 stateless Streamable HTTP，路径 `/mcp`，每次请求要求 Authorization Bearer Token。它不提供旧 SSE 或 OAuth 登录流程。

本轮提供 `mcpServers` / `url` / `headers.Authorization` 的**待本机验证配置方案**，不用未经核实的环境变量插值格式。配置示例位于 `examples/cursor/mcp.json.example`，只有占位符。启动助手生成包含真实本地 Token 的 `.cursor/mcp.json`；须由安装的 Cursor 版本验证是否识别。在验证前，不将该方案称为当前版本官方确认格式。

## Windows 最短连接步骤

前提：Windows 本机安装 Python 3.12+ 和 Cursor，检出 `work` 分支。服务与 Cursor 在同一台 Windows 主机运行；不要把云环境、WSL、容器或 SSH 远程主机的回环地址当作 Windows 主机地址。无需云服务器。

1. 在项目根目录的 PowerShell 执行：

   ```powershell
   .\scripts\start-skill-bowl.ps1
   ```

   脚本自动创建 `.venv`、安装固定版本依赖、准备两个示例 Skill、生成三个不同 Token、合并本地 `.cursor/mcp.json` 并启动服务，仅监听 `127.0.0.1:8002`。窗口需保持运行，Ctrl+C 停止。如果脚本执行被本机策略禁止，不修改执行策略，改用等价 Python 启动入口：

   ```powershell
   py -3 .\scripts\start_local.py
   ```

2. 使用 Cursor 打开同一项目根目录，在 MCP 设置中确认 `skill-bowl` 服务是否被识别并启用（具体入口以安装版本为准），必要时重新加载窗口。应显示 `list_skills` 和 `run_skill` 两个工具。若配置不被识别，先查看当前版本官方文档或 MCP 错误面板；不要将 Token 粘贴到聊天或公开 issue。由于当前无法联网核实文档，这一步必须人工确认。

3. 在 Cursor 支持工具调用的 AI 对话模式中，先请求“调用 skill-bowl 的 list_skills，列出可用 Skill”。确认实际工具调用结果包含 `writer` 和 `reviewer`。不要只接受 AI 对工具结果的口头描述；查看工具执行记录。

没有模型配置时，到这里即可验证发现与列表。运行 Skill 会返回通用工具错误，这是配置缺失的预期行为，不代表模型验收通过。Cursor 自身的 AI 对话也可能消耗其服务额度或费用，请自行确认账户政策；本轮未操作。

## 私有文件与重复运行

- 私有状态：默认 `%LOCALAPPDATA%\SkillBowl\runtime.json`，保存三个服务 Token；`skills\` 保存可修改的本地 Skill 副本，均在仓库外。
- 模型地址、名称、密钥仅继承启动进程环境，不写入 runtime.json 或 Cursor 配置。
- `.cursor/mcp.json` 含 MCP RUN Token，已被 Git 忽略；不要提交、分享或粘贴进 AI 对话。示例配置没有真实 Token。
- Windows 通过当前用户 SID 配置私有目录和新配置文件 ACL；Linux 使用 0700 目录和 0600 文件。Windows ACL 路径未在本环境实测；失败会停止启动，不绕过权限校验。
- 重复启动复用 Token，保留已有私有 Skill 修改及其他 MCP 服务。遇到已有同名 `skill-bowl` 配置且 Token 不匹配时停止，不覆盖；先在本机检查并自行备份/解决冲突。
- 如修改端口：` .\scripts\start-skill-bowl.ps1 -Port 8003`。会更新本服务配置，重新加载 Cursor 后使用新端口。端口占用时不会杀死其他程序。
- 可加 `-PrepareOnly`（Python 参数 `--prepare-only`）仅生成配置而不启动。安装依赖仍需要包仓库访问，不请求任何模型。
- Token 防护不代表本机进程隔离：具有同一用户文件访问权限的程序仍可能读取本地配置。不要把真实商业 Skill 加入 Cursor 工作区；默认私有目录放在工作区外。

## 本地协议预检（不调用模型）

服务启动后，在第二个 PowerShell 窗口运行：

```powershell
.\.venv\Scripts\python.exe -m skill_bowl.check_mcp
```

默认验证：无效 Token 被拒绝、官方 MCP 客户端 initialize、工具发现、list_skills 和两个示例 Skill 存在。它不执行 run_skill，不调用模型，输出明确保留 `cursor_ui: not_tested`。这不是 Cursor 对话框的真实接入测试。

自动回归：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

本轮在 Linux 执行；真实本地 Uvicorn/MCP 客户端传输，模型用 MockTransport。Windows 的符号链接相关测试需要系统允许创建符号链接（例如已启用开发者模式）；未在 Windows 宣称测试通过。

## 稍后配置真实模型（当前未授权执行）

仍需自己选择并确认可用的供应商、完整 HTTPS Chat Completions 地址、模型名称和 API 密钥，并确认免费政策或明确授权费用。不要向聊天发送密钥。

在用于启动服务的 PowerShell 窗口配置进程环境：

```powershell
$env:MODEL_API_URL = 'https://YOUR_PROVIDER/v1/chat/completions'
$env:MODEL_NAME = 'YOUR_MODEL'
$key = Read-Host 'Model API key' -AsSecureString
$credential = [System.Net.NetworkCredential]::new('', $key)
$env:MODEL_API_KEY = $credential.Password
Remove-Variable key, credential
.\scripts\start-skill-bowl.ps1
```

`YOUR_PROVIDER` 等必须替换，不是可用的模型配置。模型密钥会作为运行进程环境存在，不保存进仓库；使用结束后停止服务，并用 `Remove-Item Env:MODEL_API_KEY` 清除当前 shell 绑定。服务不自动读取 `.env`。

仅在确认供应商使用及费用后，可运行协议层真实执行检查：

```powershell
.\.venv\Scripts\python.exe -m skill_bowl.check_mcp --run-skills --confirm-model-call
```

该命令会执行两次模型请求；检查脚本不打印提示词、密钥或结果正文。它只能确认所配置服务返回了非空结果，不能替代 Cursor UI 验收，也不能自行证明该供应商端点不是模拟服务。本轮没有运行此真实模型模式；自动测试中的同名流程使用 MockTransport。

## Cursor 最终人工验收

配置真实模型并确认费用后，在 Cursor 对话框中分别要求：

1. 实际调用 `list_skills`，确认两个启用的 Skill。
2. 调用 `run_skill`：`skill_id=writer`、`input=为社区读书活动写一句简短介绍`，确认获得真实供应商生成结果。
3. 调用 `run_skill`：`skill_id=reviewer`、`input=审阅这句话：所有读书活动都能保证参与者成功`，确认得到不同的审阅结果。
4. 对 writer 再调用一次，传入 `previous_result` 和 `feedback=缩短到20字以内`，确认修订有效。

建议记录 Cursor 版本、配置被识别情况、实际工具执行记录、供应商及模型名称和测试时间；证据需隐藏 Token、密钥和商业 Skill 内容。不要为展示证据上传配置文件或私有指令。

## 当前验收状态

- 已完成：本地准备工具、候选 Cursor 配置、MCP 协议验证器、原有业务回归与模拟模型调用验证。共 24 项自动化测试通过；另在 Linux 临时副本中实际运行配置/启动 CLI 和默认无模型预检通过，未打印 Token。
- 额外防护：MCP 输出拦截已知 Token、模型密钥及所有已加载 Skill 完整原文的直接回显，返回通用错误；不提供资源下载。模型改写/编码泄露仍无法绝对保证阻止，沿用工作包①安全边界。
- 未完成：Cursor 官方当前文档核实、Windows/PowerShell/ACL 实测、Cursor 实际识别和对话工具调用、真实模型生成结果。
- 结论：**工作包③准备工作完成，完整端到端验收尚未通过。** 用户已选择稍后在本地验证；不把协议测试或模拟输出算作真实联调。
