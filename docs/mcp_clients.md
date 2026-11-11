# MeshScout MCP Client Configuration Guide

This guide documents Model Context Protocol (MCP) client configurations for MeshScout.
MeshScout supports dual transport modes:
1. `stdio`: Standard input/output for local desktop clients and subprocess orchestration.
2. `sse`: Server-Sent Events over HTTP for networked, containerized, or federated setups.

The MCP server exposes 14 tools, 8 resources, and 3 prompts for LoRa/MeshCore RF planning.

---

## 1. Claude Desktop

Claude Desktop connects to MeshScout via `stdio` transport.

### Configuration Path
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Option A: Direct Execution via uvx (Isolated)

```json
{
  "mcpServers": {
    "meshscout": {
      "command": "uvx",
      "args": [
        "meshscout",
        "mcp",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

### Option B: Local Repository Execution (Development)

Replace `<path-to-meshscout>` with your local repository path.

```json
{
  "mcpServers": {
    "meshscout-local": {
      "command": "python",
      "args": [
        "-m",
        "meshscout.cli",
        "mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONPATH": "<path-to-meshscout>/src"
      }
    }
  }
}
```

---

## 2. Cursor IDE

Cursor supports both local `stdio` subprocesses and remote `sse` HTTP endpoints.
Place the configuration in `.cursor/mcp.json` at the workspace root or in global Cursor settings.

### Configuration File (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "meshscout-stdio": {
      "command": "python",
      "args": [
        "-m",
        "meshscout.cli",
        "mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src"
      }
    },
    "meshscout-sse": {
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

### Starting the SSE Server for Cursor
To use the `meshscout-sse` endpoint, start the server in a terminal:

```bash
# Default bind: 127.0.0.1:8000
python -m meshscout.cli mcp --transport sse --host 127.0.0.1 --port 8000
```

Cursor connects to `GET /sse` and posts JSON-RPC calls to `POST /messages`.

---

## 3. Google Antigravity & Local Gemini CLI

Antigravity registers MCP tool schemas from dedicated tool directories under the global or workspace configuration root.

### Tool Directory Layout
Place tool schema declarations in:
- Global: `~/.gemini/antigravity/mcp/meshscout/`
- Workspace: `.gemini/antigravity/mcp/meshscout/`

Directory structure:
```text
~/.gemini/antigravity/mcp/meshscout/
|-- instructions.md
|-- scout_repeater_sites.json
|-- evaluate_link_budget.json
|-- inspect_site_feasibility.json
|-- advise_node_role_and_airtime.json
|-- recommend_backhaul_architecture.json
|-- provision_node_radio.json
|-- simulate_winter_solar_survival.json
|-- analyze_mesh_coverage_gaps.json
|-- calibrate_empirical_clutter.json
|-- generate_landowner_brief.json
|-- stage_offline_field_kit.json
|-- manage_living_mesh_state.json
|-- advise_eirp.json
`-- list_region_packs.json
```

### Antigravity Server Registration (`mcp_config.json`)

Add the stdio or SSE server definition to `~/.gemini/antigravity/mcp_config.json`:

```json
{
  "mcpServers": {
    "meshscout": {
      "command": "python",
      "args": [
        "-m",
        "meshscout.cli",
        "mcp",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONPATH": "<path-to-meshscout>/src"
      }
    }
  }
}
```

### Sample Lazy Tool Schema (`scout_repeater_sites.json`)

```json
{
  "name": "scout_repeater_sites",
  "description": "Scout and optimize regional repeater high-sites using offline viewsheds and weighted set-cover.",
  "parameters": {
    "type": "object",
    "properties": {
      "region": {
        "type": "string",
        "default": "vt_chittenden",
        "description": "Target county or geographic basin identifier."
      },
      "min_coverage": {
        "type": "number",
        "default": 0.90,
        "description": "Target population or land basin coverage fraction (0.0 to 1.0)."
      },
      "max_repeaters": {
        "type": "integer",
        "default": 5,
        "description": "Maximum number of repeaters to select."
      },
      "no_delay": {
        "type": "boolean",
        "default": true,
        "description": "Bypass rate-limiting jitter for offline execution."
      }
    },
    "required": ["region"]
  }
}
```

---

## 4. Federated Gateway and Reverse Proxy

When deploying MeshScout in networked multi-agent environments, tools route through an HTTPS reverse proxy (such as Traefik, Caddy, or Nginx).

### Architecture Overview
1. `MeshScout SSE Server` runs as an internal service: `python -m meshscout.cli mcp --transport sse --host 0.0.0.0 --port 8000`.
2. `Reverse Proxy` terminates TLS and routes `https://example.invalid/meshscout/` to the SSE server.
3. MCP clients connect directly to the HTTPS endpoint or via a secure tunnel.

### Traefik Ingress Configuration (`traefik-meshscout.yml`)

```yaml
http:
  routers:
    meshscout-router:
      rule: "Host(`example.invalid`) && PathPrefix(`/meshscout`)"
      entryPoints:
        - "websecure"
      service: "meshscout-service"
      tls:
        certResolver: "letsencrypt"

  services:
    meshscout-service:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8000"
```

---

## Verification Matrix

| Client | Transport | Connection Method | Verification Command |
| :--- | :--- | :--- | :--- |
| **Claude Desktop** | `stdio` | Subprocess pipe | Check hammer icon in Claude chat |
| **Cursor** | `stdio` | Subprocess pipe | Cursor Settings > Features > MCP |
| **Cursor** | `sse` | HTTP `/sse` stream | Check green status indicator in Cursor MCP tab |
| **Antigravity** | `stdio` | MCP registry | Call `scout_repeater_sites` via agent tool |
| **Remote Gateway** | `sse` | Reverse proxy | Query `POST /messages` with JSON-RPC payload |
