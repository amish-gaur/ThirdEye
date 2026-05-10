"""SafeWatch MCP server.

Exposes cross-camera person search to any MCP client (Claude Desktop,
Claude.ai, Claude Code). Tools are thin adapters over `search.core`
so the same logic also drives the FastAPI HTTP fallback used as
demo-day insurance.
"""
