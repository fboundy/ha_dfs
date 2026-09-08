#!/usr/bin/env python3
"""Copy the neso_dfs library into the integration's vendor_lib directory.

HACS installs an integration by copying custom_components/<domain>/ from the repo, so the
integration has to be self-contained. The library at the repo root stays the source of truth;
run this after changing it. tests/test_vendor_sync.py fails if the two drift apart.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

MODULES = ("__init__.py", "api.py", "bids.py", "events.py", "zones.py")

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "neso_dfs"
VENDOR_DIR = REPO_ROOT / "custom_components" / "neso_dfs" / "vendor_lib"


def sync() -> list[str]:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    changed = []
    for module in MODULES:
        source = SOURCE_DIR / module
        target = VENDOR_DIR / module
        if not target.exists() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
            changed.append(module)
    return changed


if __name__ == "__main__":
    updated = sync()
    print(f"vendor_lib up to date ({len(updated)} file(s) updated)")
    sys.exit(0)
