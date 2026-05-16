"""activegraph CLI. CONTRACT v0.8 #12.

A thin wrapper around library APIs. No business logic in the CLI — every
subcommand calls into the library and formats the result. Programmatic
users do exactly the same things the CLI does.

Entry point is wired via ``[project.scripts]`` in pyproject:

    activegraph = "activegraph.cli.main:main"

So ``activegraph inspect ...`` runs ``activegraph.cli.main:main`` with
the rest of argv.
"""

from activegraph.cli.main import main, EXIT_CODES

__all__ = ["main", "EXIT_CODES"]
