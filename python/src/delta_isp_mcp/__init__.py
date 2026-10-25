"""Delta ISPSoft MCP server.

The package is split into layers so each one can be tested without the IDE:

    isp.container  .isp container <-> project source text
    isp.project    project source text -> POU / TASK / PROJECT model
    isp.symbols    global symbols and DUT names
    lint.st_check  cheap pre-flight checks for ST code
    safety         workspace, hashes, process locks
    service        stateful operations used by the MCP tools and the CLI
    server         MCP (stdio) surface
    cli            human-facing command line
"""

__version__ = "0.2.1"
