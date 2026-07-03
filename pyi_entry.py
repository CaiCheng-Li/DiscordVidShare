"""PyInstaller entry point.

Uses an absolute import so PyInstaller's static analysis follows it into the
`discordvidshare` package (a relative import in a top-level script is not
resolved during analysis, which would leave PySide6/Qt out of the bundle).
"""

from discordvidshare.app import main

if __name__ == "__main__":
    raise SystemExit(main())
