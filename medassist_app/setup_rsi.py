#!/usr/bin/env python3
"""
setup_rsi.py — Copy rsi_mapping.json from the MedFT data directory
into this folder so the frontend can access it standalone.

Run this once from inside the pv_frontend/ folder:
    python setup_rsi.py
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "data", "rsi_mapping.json")
DEST   = os.path.join(HERE, "rsi_mapping.json")

def main():
    if os.path.exists(DEST):
        size_mb = os.path.getsize(DEST) / 1_048_576
        print(f"✅ rsi_mapping.json already exists ({size_mb:.1f} MB). Nothing to do.")
        return

    if not os.path.exists(SOURCE):
        print(f"❌ Source not found: {SOURCE}")
        print("   Make sure you have run the MedFT pipeline at least once (extract_rsi.py).")
        sys.exit(1)

    print(f"Copying rsi_mapping.json ({os.path.getsize(SOURCE)/1_048_576:.1f} MB)…")
    shutil.copy2(SOURCE, DEST)
    print(f"✅ Copied to: {DEST}")

if __name__ == "__main__":
    main()
