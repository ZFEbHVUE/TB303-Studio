#!/usr/bin/env python3
"""Launch the Mk III front panel from this folder, even if an older edition is installed."""
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "Python_Scripts"))
    from tb303_studio import main
    main()
