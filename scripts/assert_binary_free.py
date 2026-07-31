from __future__ import annotations

import os
import sys
from pathlib import Path

SKIP_ROOTS = {
    Path("/dev"),
    Path("/proc"),
    Path("/sys"),
}
FORBIDDEN_NAMES = {"chrome", "chrome-wrapper", "chromium", "chromium-browser"}


def main() -> int:
    findings: list[str] = []
    for root, directories, files in os.walk("/", topdown=True, onerror=lambda _: None):
        root_path = Path(root)
        directories[:] = [name for name in directories if root_path / name not in SKIP_ROOTS]
        for name in directories:
            path = root_path / name
            lowered = name.lower()
            if ".cloakbrowser" in path.parts and lowered.startswith("chromium-"):
                findings.append(str(path))
        for name in files:
            path = root_path / name
            lowered = name.lower()
            if lowered in FORBIDDEN_NAMES:
                findings.append(str(path))
            if ".cloakbrowser" in path.parts and lowered.startswith("chromium-"):
                findings.append(str(path))

    if findings:
        print("CloakBrowser Chromium binary found in image:", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(f"- {finding}", file=sys.stderr)
        return 1

    print("binary-free check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
