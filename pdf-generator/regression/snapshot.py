#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
BASELINES = Path(__file__).resolve().parent / "baselines"
BASELINES.mkdir(parents=True, exist_ok=True)


def copy_if_exists(src: Path, dst: Path):
    if src.exists():
        shutil.copy2(src, dst)
        print(f"Saved {dst.name}")
        return True
    return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 regression/snapshot.py PROJECTNAME")
        sys.exit(1)

    project = sys.argv[1].upper()
    saved_any = False
    saved_any |= copy_if_exists(ROOT / f"{project}_pipeline.json", BASELINES / f"{project}_pipeline.json")
    saved_any |= copy_if_exists(ROOT / f"{project}_estimate.json", BASELINES / f"{project}_estimate.json")

    if not saved_any:
        print(f"No matching files found for {project}")
        sys.exit(1)


if __name__ == "__main__":
    main()
