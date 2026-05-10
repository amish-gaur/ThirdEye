"""Cross-camera person search.

Two transports call into the same `core.SearchEngine`:
    - mcp_server/server.py  (Claude Desktop / Claude.ai / Claude Code)
    - FastAPI HTTP routes   (curl / wifi-fail demo fallback)

The engine reads from `vision_pipeline.track_store.TrackStore` (SQLite WAL).
"""
