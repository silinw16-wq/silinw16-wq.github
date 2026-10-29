# 工作包②：兼容性调查记录

调查日期：2026-10-29。调查环境为受限网络；未购买服务，未创建 WorkBuddy 连接。

## WorkBuddy：待验证

尝试访问资料入口：

- https://www.codebuddy.ai/
- https://www.codebuddy.cn/

两次 HTTPS CONNECT 均被代理返回 **403 Forbidden**，未取得页面内容。它们是本次尝试的资料入口，不能作为已核实 WorkBuddy 接入规范的证据。当前没有可用的官方全文检索工具。未修改网络策略或绕过代理。

以下事项均**待官方资料或实际客户端验证**，本项目不猜测配置字段：

| 项目 | 状态 |
| --- | --- |
| 自定义 MCP 的界面入口、配置格式及版本要求 | 待验证 |
| 是否支持远程 Streamable HTTP，是否还要求旧 HTTP+SSE | 待验证 |
| 是否支持自定义 Authorization: Bearer 请求头 | 待验证 |
| 是否必须 OAuth、动态注册或其他认证方式 | 待验证 |
| HTTPS、域名、代理及证书限制 | 待验证 |

因此本轮交付的是已通过本地 MCP 协议测试的通用服务端，**不宣称 WorkBuddy 已兼容或已联调成功**。后续应在允许访问的环境阅读 WorkBuddy 当前版本官方 MCP 资料，记录具体文档 URL、版本、传输及认证说明；若客户端只支持 OAuth 或旧 SSE，须另行评估，不默认本实现可直接使用。

## 已核实：官方 Python MCP SDK

已读取官方仓库的固定版本 README：

- https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.0/README.md
- 实际获取：https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v1.29.0/README.md

README 的 Overview 明确支持 stdio、SSE、Streamable HTTP，Quickstart 示例使用 `mcp.run(transport="streamable-http")`。同时检查本机 `mcp==1.29.0` 的 `FastMCP.streamable_http_app`、会话管理器及官方客户端 `streamable_http_client`，并通过本地真实 HTTP 请求验证 initialize、tools/list、tools/call 等协议流程。

选择：固定 `mcp==1.29.0`，使用 FastMCP 的 **stateless Streamable HTTP + JSON response**，端点 `/mcp`。不提供旧 `/sse`、WebSocket 或 stdio 入口。该选择已确认适用于所用官方 SDK，是否适用于 WorkBuddy 仍待验证。

## 授权范围

本实现使用管理员预置的不透明 Bearer Token（非 JWT、非 OAuth），不会声称实现 MCP OAuth 授权服务器：

- 独立的 MCP RUN Token：可发现工具、查询 Skill、执行 Skill。
- 可选 MCP READ Token：可发现工具、查询 Skill，执行返回工具错误且不调用模型。
- REST Token 与两种 MCP Token 必须互不相同；REST Token 不能访问 MCP。
- 同一服务内的 Token 是能力权限，不是多租户或按 Skill 用户隔离。

无凭据、无效凭据及重复 Authorization 头在协议分派前拒绝；每次请求重新认证，不使用会话 ID 授权。未实现 Token 签发、轮换接口、撤销列表、OAuth 元数据或用户管理。轮换通过更新环境变量及重启实现。

## 验证等级

1. 原工作包①：模拟上游模型的业务单元测试。
2. 本工作包②：官方 MCP 客户端连接真实本地 Uvicorn Streamable HTTP 服务；模型仍为 MockTransport。该测试不是模拟 MCP JSON 方法直接调用。
3. WorkBuddy 实际连接：未执行（本轮明确不在范围内）。
4. 真实模型 API：未执行，未使用付费模型。
