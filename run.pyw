# -*- coding: utf-8 -*-
"""hardwareWatch launcher (pythonw run.pyw)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hardwarewatch.main import main

if __name__ == "__main__":
    sys.exit(main())
