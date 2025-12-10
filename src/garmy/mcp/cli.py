#!/usr/bin/env python3
"""Command-line interface for Garmin LocalDB MCP Server."""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .config import MCPConfig

try:
    from .server import create_mcp_server
except ImportError:

    def create_mcp_server(*args, **kwargs):
        raise ImportError(
            "FastMCP is required for MCP server functionality. "
            "Install with: pip install garmy[mcp] or pip install fastmcp"
        )


def resolve_db_path(args) -> Optional[str]:
    """Resolve database path from arguments.

    Priority:
    1. --database CLI argument
    2. --profile-path CLI argument (derives <profile>/health.db)
    3. GARMY_PROFILE_PATH environment variable (derives <profile>/health.db)
    4. GARMY_DB_PATH environment variable

    Args:
        args: Parsed command-line arguments

    Returns:
        Database path string or None if not resolvable
    """
    # Priority 1: Explicit database path
    if args.database:
        return args.database

    # Priority 2: Profile path from CLI
    profile_path = getattr(args, "profile_path", None)
    if profile_path:
        return str(Path(profile_path).expanduser() / "health.db")

    # Priority 3: Profile path from environment
    env_profile = os.environ.get("GARMY_PROFILE_PATH")
    if env_profile:
        return str(Path(env_profile).expanduser() / "health.db")

    # Priority 4: Database path from environment
    return os.environ.get("GARMY_DB_PATH")


def validate_database_path(db_path: str) -> Path:
    """Validate database path exists and is accessible.

    Args:
        db_path: Path to SQLite database file

    Returns:
        Validated Path object

    Raises:
        FileNotFoundError: If database file doesn't exist
        PermissionError: If database file is not readable
    """
    path = Path(db_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    if not os.access(path, os.R_OK):
        raise PermissionError(f"Database file is not readable: {path}")

    return path


def cmd_server(args):
    """Start MCP server with specified configuration."""
    # Resolve database path from arguments/environment
    db_path_str = resolve_db_path(args)

    if not db_path_str:
        print(
            "Error: Database path must be provided via --database, --profile-path, "
            "or GARMY_DB_PATH/GARMY_PROFILE_PATH environment variable",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # Validate database path
        db_path = validate_database_path(db_path_str)

        # Validate configuration parameters
        if args.max_rows > args.max_rows_absolute:
            print(
                f"Error: --max-rows ({args.max_rows}) cannot exceed --max-rows-absolute ({args.max_rows_absolute})",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.max_rows <= 0:
            print("Error: --max-rows must be positive", file=sys.stderr)
            sys.exit(1)

        if args.max_rows_absolute > 10000:
            print(
                "Error: --max-rows-absolute cannot exceed 10000 for security reasons",
                file=sys.stderr,
            )
            sys.exit(1)

        # Validate transport configuration
        if args.transport in ("http", "sse"):
            # Validate port range
            if args.port < 1 or args.port > 65535:
                print("Error: --port must be between 1 and 65535", file=sys.stderr)
                sys.exit(1)

            # Warn about privileged ports
            if args.port < 1024:
                print(
                    "Warning: Ports below 1024 may require root privileges",
                    file=sys.stderr,
                )

            # Security warning for network exposure
            if args.host == "0.0.0.0":
                print("=" * 60, file=sys.stderr)
                print("⚠️  SECURITY WARNING", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                print(
                    "Binding to 0.0.0.0 exposes the server to your entire network.",
                    file=sys.stderr,
                )
                print(
                    "The MCP protocol does not provide authentication or encryption.",
                    file=sys.stderr,
                )
                print(
                    "Anyone on your network can access your health data.",
                    file=sys.stderr,
                )
                print("", file=sys.stderr)
                print("Recommendations:", file=sys.stderr)
                print("  - Use firewall rules to restrict access", file=sys.stderr)
                print("  - Use SSH tunneling for remote access", file=sys.stderr)
                print("  - Consider using 127.0.0.1 for localhost-only", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                print("", file=sys.stderr)

        # Create config with CLI parameters
        config = MCPConfig(
            db_path=db_path,
            max_rows=args.max_rows,
            max_rows_absolute=args.max_rows_absolute,
            enable_query_logging=args.enable_query_logging,
            strict_validation=not args.disable_strict_validation,
            transport=args.transport,
            host=args.host,
            port=args.port,
        )

        if args.verbose:
            print("Starting Garmin LocalDB MCP Server...")
            print(f"Database: {db_path}")
            print("Configuration:")
            print(f"  - Read-only access: enabled")
            print(f"  - Max rows per query: {config.max_rows}")
            print(f"  - Max rows absolute limit: {config.max_rows_absolute}")
            print(f"  - Query logging: {config.enable_query_logging}")
            print(f"  - Strict validation: {config.strict_validation}")
            print(f"  - Transport: {config.transport}")

            # Show network details for non-stdio transports
            if config.transport in ("http", "sse"):
                print(f"  - Host: {config.host}")
                print(f"  - Port: {config.port}")
                print("")
                print("Network Access:")
                print(f"  - Server URL: http://{config.host}:{config.port}")
                if config.transport == "sse":
                    print(f"  - SSE Endpoint: http://{config.host}:{config.port}/sse")
                print("")
                if config.host == "127.0.0.1":
                    print("Note: Server bound to localhost only (127.0.0.1)")
                    print("      Use --host 0.0.0.0 for network access")
                elif config.host == "0.0.0.0":
                    print("WARNING: Server exposed on ALL network interfaces")
                print("")

            print(
                "Available tools: explore_database_structure, get_table_details, "
                "execute_sql_query, get_health_summary"
            )

        # Create and run server with explicit config
        mcp_server = create_mcp_server(config)

        # Run with transport configuration
        if config.transport == "stdio":
            mcp_server.run()
        else:
            mcp_server.run(
                transport=config.transport,
                host=config.host,
                port=config.port,
            )

    except (FileNotFoundError, PermissionError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Failed to start MCP server: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_info(args):
    """Show information about the database and MCP server configuration."""
    # Resolve database path from arguments/environment
    db_path_str = resolve_db_path(args)

    if not db_path_str:
        print(
            "Error: Database path must be provided via --database, --profile-path, "
            "or GARMY_DB_PATH/GARMY_PROFILE_PATH environment variable",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        db_path = validate_database_path(db_path_str)

        # Get database info
        file_size = db_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)

        print("Garmin LocalDB MCP Server Information")
        print("=" * 40)
        print(f"Database file: {db_path}")
        print(f"File size: {file_size_mb:.2f} MB")
        print(
            f"Read access: {'✅ Available' if os.access(db_path, os.R_OK) else '❌ Denied'}"
        )

        # Try to get table info
        try:
            from .server import DatabaseManager

            config = MCPConfig.from_db_path(db_path)
            db_manager = DatabaseManager(config)

            # Get table information
            tables_query = (
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = db_manager.execute_safe_query(tables_query)

            print(f"\\nAvailable tables: {len(tables)}")
            for table in tables:
                table_name = table["name"]
                count_query = f"SELECT COUNT(*) as count FROM {table_name}"
                count_result = db_manager.execute_safe_query(count_query)
                row_count = count_result[0]["count"] if count_result else 0
                print(f"  - {table_name}: {row_count:,} records")

        except Exception as e:
            print(f"\\nWarning: Could not analyze database structure: {e}")

        print("\\nMCP Server Tools:")
        print("  - explore_database_structure() - Discover available data")
        print("  - get_table_details(name) - Get table schema and samples")
        print("  - execute_sql_query(sql, params) - Run SQL queries safely")
        print("  - get_health_summary(user_id, days) - Quick health overview")

        print("\\nTo start MCP server:")
        print(f"  garmy-mcp server --database {db_path}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_config(args):
    """Show example configurations for different use cases."""
    print("Garmin LocalDB MCP Server - Configuration Examples")
    print("=" * 50)

    print("\n📋 Basic Usage (stdio - for Claude Desktop):")
    print("  garmy-mcp server --database health.db")
    print("  garmy-mcp server --profile-path ~/Services/Garmy/profiles/user1")

    print("\n🌐 Network Usage (HTTP transport):")
    print("  # Localhost only (secure)")
    print("  garmy-mcp server --database health.db --transport http --port 8000")
    print("")
    print("  # Local network (WARNING: no authentication)")
    print("  garmy-mcp server --database health.db --transport http \\\\")
    print("    --host 0.0.0.0 --port 8080")

    print("\n🔒 Secure Remote Access (via SSH tunnel):")
    print("  # On remote server:")
    print("  garmy-mcp server --database health.db --transport http --port 8000")
    print("")
    print("  # On local machine:")
    print("  ssh -L 8000:localhost:8000 user@remote-server")
    print("  # Then connect to http://localhost:8000 locally")

    print("\n🏭 Production Configuration (restrictive):")
    print("  garmy-mcp server --database health.db \\\\")
    print("    --max-rows 100 \\\\")
    print("    --max-rows-absolute 500")

    print("\n🔧 Development Configuration (permissive with logging):")
    print("  garmy-mcp server --database health.db \\\\")
    print("    --transport http --port 8000 \\\\")
    print("    --max-rows 2000 \\\\")
    print("    --enable-query-logging \\\\")
    print("    --verbose")

    print("\n🤖 Claude Desktop Integration (stdio):")
    print("  {")
    print('    "mcpServers": {')
    print('      "garmy-localdb": {')
    print('        "command": "garmy-mcp",')
    print(
        '        "args": ["server", "--profile-path", "/path/to/profiles/user1"]'
    )
    print("      }")
    print("    }")
    print("  }")

    print("\n🔐 Security Settings:")
    print("  --max-rows: Limit rows per query (default: 1000, max: 5000)")
    print("  --max-rows-absolute: Hard security limit (default: 5000, max: 10000)")
    print("  --enable-query-logging: Log all SQL queries for debugging")

    print("\n🌐 Network Transport Settings:")
    print("  --transport: stdio (default), http (recommended), or sse (legacy)")
    print("  --host: IP address to bind (default: 127.0.0.1)")
    print("  --port: Port number (default: 8000)")
    print("")
    print("  WARNING: Network transports expose health data without authentication.")
    print("  Use localhost binding (127.0.0.1) and SSH tunneling for remote access.")


def create_parser():
    """Create argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="garmy-mcp",
        description="Garmin LocalDB MCP Server - Secure read-only access to health data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local stdio transport (default, for Claude Desktop)
  garmy-mcp server --database health.db
  garmy-mcp server --profile-path ~/profiles/user1

  # HTTP network transport
  garmy-mcp server --database health.db --transport http --port 8000

  # HTTP on local network (all interfaces)
  garmy-mcp server --database health.db --transport http --host 0.0.0.0 --port 8080

  # Info and config commands
  garmy-mcp info --database health.db
  garmy-mcp config

Environment Variables:
  GARMY_PROFILE_PATH    Profile directory path (derives database as <profile>/health.db)
  GARMY_DB_PATH         Direct database path

Security Note:
  Network transports (http/sse) expose health data without authentication.
  Use localhost binding (127.0.0.1) and SSH tunneling for remote access.

Use 'garmy-mcp <command> --help' for command-specific help.
        """,
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True

    # Server command
    server_parser = subparsers.add_parser(
        "server",
        help="Start MCP server",
        description="Start the MCP server with specified configuration",
    )

    server_parser.add_argument(
        "--profile-path",
        type=str,
        help="Path to profile directory. Database path derived as <profile>/health.db. "
        "Can also be set via GARMY_PROFILE_PATH environment variable.",
    )
    server_parser.add_argument(
        "--database", "-d", type=str, help="Path to Garmin LocalDB SQLite database file"
    )

    server_parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        help="Maximum number of rows per query (default: 1000, max: 5000)",
    )

    server_parser.add_argument(
        "--max-rows-absolute",
        type=int,
        default=5000,
        help="Absolute maximum rows limit for security (default: 5000, max: 10000)",
    )

    server_parser.add_argument(
        "--enable-query-logging",
        action="store_true",
        help="Enable SQL query logging for debugging",
    )

    server_parser.add_argument(
        "--disable-strict-validation",
        action="store_true",
        help="Disable strict SQL validation (not recommended)",
    )

    server_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging and configuration display",
    )

    server_parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport protocol: stdio (default, for Claude Desktop), "
        "http (recommended for network), or sse (legacy network)",
    )

    server_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind for network transports (default: 127.0.0.1). "
        "Use 0.0.0.0 to expose on all interfaces (WARNING: no authentication)",
    )

    server_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for network transports (default: 8000, range: 1024-65535 recommended)",
    )

    server_parser.set_defaults(func=cmd_server)

    # Info command
    info_parser = subparsers.add_parser(
        "info",
        help="Show database and server information",
        description="Display information about the database and available MCP tools",
    )

    info_parser.add_argument(
        "--profile-path",
        type=str,
        help="Path to profile directory. Database path derived as <profile>/health.db. "
        "Can also be set via GARMY_PROFILE_PATH environment variable.",
    )
    info_parser.add_argument(
        "--database", "-d", type=str, help="Path to Garmin LocalDB SQLite database file"
    )

    info_parser.set_defaults(func=cmd_info)

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Show configuration examples",
        description="Display example configurations for different use cases",
    )
    config_parser.set_defaults(func=cmd_config)

    return parser


def main():
    """Main entry point for garmy-mcp CLI."""
    parser = create_parser()
    args = parser.parse_args()

    # Execute the selected command
    args.func(args)


if __name__ == "__main__":
    main()
