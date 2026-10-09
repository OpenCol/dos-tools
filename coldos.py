#!/usr/bin/env python3
"""Run coldos without installing it: `python3 coldos.py ...`"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coldos.cli import main                                    # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
