<p align="center">
  <img src="../../../../assets/blog/homepilot-compatible-badge.svg" alt="HomePilot MCP Compatible" width="280" />
</p>

# MCP Web Fetch

**Fetch and extract clean text from web pages — with SSRF protection.**

| | |
| :--- | :--- |
| **Server name** | `homepilot-web` |
| **Default port** | `9112` |
| **Persona** | Maya Chen — *Web Researcher* |
| **Role** | `assistant` |
| **Protocol** | JSON-RPC 2.0 (MCP v1) |

---

## What It Does

The Web Fetch MCP server enables your AI Persona to retrieve web content and extract readable text from HTML pages. It includes built-in SSRF (Server-Side Request Forgery) protection that blocks requests to localhost, private IP ranges, and link-local addresses.

Use this when your Persona needs to read a web page, extract the main article text, or fetch data from a public URL.

---

## Tools

| Tool | Description | Write-Gated |
| :--- | :--- | :---: |
| `hp.web.fetch` | Fetch raw HTML and headers from a URL | No |
| `hp.web.extract_main` | Extract main article text from a URL or raw HTML | No |

### Tool Details

**`hp.web.fetch`**
```json
{
  "url": "https://example.com/article"
}
```
Returns raw HTML content. Respects `MAX_DOWNLOAD_BYTES` and `REQUEST_TIMEOUT` limits.

**`hp.web.extract_main`**
```json
{
  "url_or_html": "https://example.com/article"
}
```
Accepts either a URL or raw HTML string. When given HTML, strips tags and returns clean text (up to 5,000 characters).

---

## Installation

### Quick Start

```bash
cd agentic/integrations/mcp/web

cp .env.example .env
make install
make run
```

The server starts on `http://0.0.0.0:9112` by default.

---

## Configuration

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `9112` | Server port |
| `REQUEST_TIMEOUT` | `15` | HTTP request timeout in seconds |
| `MAX_DOWNLOAD_BYTES` | `5242880` | Maximum download size (5 MB) |
| `DENY_INTERNAL_IPS` | `true` | Block requests to localhost and private IPs (SSRF protection) |

### Security

- **SSRF Protection**: When `DENY_INTERNAL_IPS=true` (default), the server blocks requests to `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`, and `169.254.*` addresses.
- **Size Limits**: Downloads are capped at `MAX_DOWNLOAD_BYTES` to prevent memory exhaustion.
- **Timeout**: Requests time out after `REQUEST_TIMEOUT` seconds.

---

## Testing

```bash
make test
```

---

## Project Structure

```
web/
├── app.py            # Server implementation with SSRF protection
├── pyproject.toml    # Dependencies and project metadata
├── Makefile          # Install, test, run, clean, lint targets
├── .env.example      # Configuration template
├── __init__.py
└── tests/            # Test suite
```

---

## Part of the HomePilot Ecosystem

This server is one of 17 MCP tool servers in the HomePilot platform. It connects through the **Context Forge** gateway (port 4444).

---

<p align="center">
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/HomePilot">GitHub</a> · <a href="../../../../docs/INTEGRATIONS.md">Integrations Guide</a>
</p>
