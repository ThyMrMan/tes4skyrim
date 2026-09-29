"""List all file paths inside a BSA (v103/104/105) — names only, no data.

Usage: python tools/misc/bsa_list_names.py <bsa> [substring-filter]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from asset_convert.sources.bsa_extract import read_bsa_directory


def list_names(bsa_path):
    """Every file path inside the BSA, in directory order."""
    with open(bsa_path, 'rb') as fh:
        return [entry[0] for entry in read_bsa_directory(fh)[2]]


if __name__ == '__main__':
    filt = sys.argv[2].lower() if len(sys.argv) > 2 else ''
    for n in list_names(sys.argv[1]):
        if filt in n.lower():
            print(n)
