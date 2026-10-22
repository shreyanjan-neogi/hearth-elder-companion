# Friction log

Things we actually hit while building Hearth. Each entry says what we tried, what we expected, what happened,
how bad it was, and what we did about it. (Edit or add to this as you keep building. Only real experiences belong here.)

## 1. `FastMCP` import fails on the newest Python MCP SDK

- **Task:** write a first MCP server in Python.
- **Steps:** `pip install mcp` (installed 2.3.0), then the commonly shown `from mcp.server.fastmcp import FastMCP`.
- **Expected:** the usual quickstart code runs.
- **Actual:** `ModuleNotFoundError`. The message was genuinely helpful: it explained that FastMCP was renamed to
  `MCPServer` in 2.x, linked a migration guide, and said how to pin `mcp<2`.
- **Severity:** low to medium. About five minutes lost, but a lot of existing tutorials, blog posts and AI assistants
  still use the old name, so many newcomers will hit this.
- **Workaround:** `from mcp.server.mcpserver import MCPServer`.
- **Suggestion:** keep a deprecated `FastMCP` alias for a release or two that warns instead of failing, and mention the
  rename at the top of the Python quickstart.

## 2. A tool that returns a plain `dict` gives no `structured_content`

- **Task:** read tool results in the client, in code.
- **Steps:** a tool returns a normal Python `dict`; the client calls it with `call_tool`.
- **Expected:** the dict arrives as structured data.
- **Actual:** `result.structured_content` is `None` and the tool has no output schema. The data arrives only as JSON
  text in `result.content[0].text`.
- **Severity:** low. We may have missed a setting or a documented way to turn this on.
- **Workaround:** parse the JSON text.
- **Suggestion:** document that bare `dict` returns are text-only and that a typed return (for example a model or
  `TypedDict`) is what produces structured output. A one-line note in the tool-writing guide would have saved us time.

## 3. Positive: in-process testing and protocol negotiation

- Passing the `MCPServer` object straight into `Client(...)` made early tests very fast, and `Client(url)` over
  Streamable HTTP worked the first time. `client.protocol_version` made it easy to prove, in a test, that we meet the
  hackathon's "spec 2025-11-25 or later" requirement.

## 4. Not tested: real Alexa+

- We did not test against a real Alexa+ device or the Alexa+ Preview. The assistant in this repo is a simulator, and
  we have no feedback to give on Alexa+ onboarding, tooling or certification from direct experience.
