#!/usr/bin/env python3
"""Open the photographic Roland panel using this copy of the Studio."""
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "Python_Scripts"))
    from tb303_studio import main
    sys.argv.append("--roland-panel")
    main()
