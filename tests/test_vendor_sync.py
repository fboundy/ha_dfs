from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "neso_dfs"
VENDOR_DIR = REPO_ROOT / "custom_components" / "neso_dfs" / "vendor_lib"
MODULES = ("__init__.py", "api.py", "events.py", "zones.py")


@pytest.mark.parametrize("module", MODULES)
def test_vendored_module_matches_source(module):
    """HACS ships custom_components/ as-is, so the vendored copy must not drift."""
    vendored = VENDOR_DIR / module
    assert vendored.exists(), f"{module} missing - run scripts/sync_vendor.py"
    assert vendored.read_bytes() == (SOURCE_DIR / module).read_bytes(), (
        f"{module} has drifted - run scripts/sync_vendor.py"
    )
