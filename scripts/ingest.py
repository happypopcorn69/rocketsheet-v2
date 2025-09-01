#!/usr/bin/env python3
"""
ingest.py
==========

This module provides a tiny MVP parser that forwards to the v2
implementation.  It exists primarily for backwards compatibility with
older scripts and documentation.  If you are starting a new project
please use ``ingest_v2.py`` directly.
"""

import subprocess
import sys


def main() -> None:
    # Dispatch to ingest_v2.py while preserving CLI arguments.  This
    # simple wrapper allows existing command lines to continue to work
    # without modification.  If ``ingest_v2.py`` is not found the call
    # will fail and propagate an error to the caller.
    try:
        script = __file__.replace("ingest.py", "ingest_v2.py")
        cmd = [sys.executable, script] + sys.argv[1:]
        sys.exit(subprocess.call(cmd))
    except Exception as exc:
        sys.stderr.write(f"Failed to launch ingest_v2.py: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
