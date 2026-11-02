"""What the packaged programs run. PyInstaller needs a script, not a console entry point."""

import sys

from drivion.app import main

sys.exit(main())
