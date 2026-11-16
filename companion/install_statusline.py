"""Kept for compatibility: same as `python install_claude.py statusline [--remove]`."""
import sys

import install_claude

if __name__ == "__main__":
    install_claude.main(["statusline"] + sys.argv[1:])
