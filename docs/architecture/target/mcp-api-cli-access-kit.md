---
title: MCP/API/CLI Access Kit
slug: mcp-api-cli-access-kit
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# MCP/API/CLI Access Kit

## Target State

The access kit provides programmatic access to the Aether intelligence
graph through multiple surfaces: REST API, MCP (Model Context Protocol)
server, and CLI tool.

## Planned Surfaces

### REST API

- `/v1/batch` — observation ingestion (existing)
- `/v1/entities` — entity query and lookup
- `/v1/graph` — graph query and traversal
- `/v1/campaigns` — campaign management
- `/v1/agents` — agent lifecycle management

### MCP Server

An MCP server that exposes Aether graph queries and entity lookups to
LLM-based tools and agents.

### CLI Tool

A command-line tool for developers to interact with tenant graph state,
run diagnostics, and manage configurations.

## Architecture

```
Access surface (API / MCP / CLI)
→ Authentication + tenant resolution
→ Query router
→ Graph query engine
→ Response serialization
```

## Dependencies

- Graph query surfaces
- Tenant authentication
- API versioning and contract governance
