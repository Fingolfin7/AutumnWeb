"""Compatibility entry point for the packaged Autumn MCP server.

The canonical implementation lives in the Autumn CLI package
(autumn_cli.mcp_server), built on the v2 API client facade. This shim keeps
existing MCP configurations that point at this file working. Install the CLI
with the mcp extra (pip install -e <autumn-repo>/cli[mcp]) or keep a checkout
of the Autumn CLI repo next to this one.
"""

try:
    from autumn_cli.mcp_server import main, mcp  # noqa: F401
except ModuleNotFoundError as exc:
    if exc.name != "autumn_cli":
        raise
    import sys
    from pathlib import Path

    # Fall back to a sibling checkout of the Autumn CLI repo.
    sibling = Path(__file__).resolve().parent.parent / "Autumn" / "cli"
    sys.path.insert(0, str(sibling))
    from autumn_cli.mcp_server import main, mcp  # noqa: F401


if __name__ == "__main__":
    main()
