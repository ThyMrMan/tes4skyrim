"""Extract compiled-in default values for Bethesda settings from a 64-bit exe.

Each setting is registered by a dynamic initializer thunk:
    sub rsp,0x28
    movss xmm2, [rip+X]        ; float default   (or mov r8d,imm / xor r8d,r8d for int)
    lea   rdx, [rip+name]      ; "fFoo:Section" (INI) or "fFoo" (game setting)
    lea   rcx, [rip+object]    ; the Setting object
    call  Setting::ctor
so the default is recoverable from the single lea that references the name.

Usage:
    python tools/disasm/ck_settings_dump.py --filter NavMeshGeneration
    python tools/disasm/ck_settings_dump.py --exe <SkyrimSE.exe> --pattern "fCombat\\w*Chance(Min|Max)"
"""
import argparse
import re
import struct
import sys

import numpy as np
import pefile
from capstone import CS_ARCH_X86, CS_MODE_64, Cs

DEFAULT_EXE = (r'C:\Program Files (x86)\Steam\steamapps\common'
               r'\Skyrim Special Edition\CreationKit.exe')

#: An INI setting name, "fName:Section".
_INI_NAME = r'[!-~][ -~]{2,80}:[A-Za-z]+'


class Image:
    """The exe's raw bytes plus RVA <-> file-offset mapping."""

    def __init__(self, path: str):
        """Load `path` and index its sections."""
        pe = pefile.PE(path, fast_load=True)
        self.image_base = pe.OPTIONAL_HEADER.ImageBase
        self.data = open(path, 'rb').read()
        self.secs = [(s.VirtualAddress, s.Misc_VirtualSize, s.PointerToRawData,
                      s.SizeOfRawData, s.Name.rstrip(b'\0').decode()) for s in pe.sections]

    def r2o(self, rva: int):
        """File offset of `rva`, None when it is not backed by file data."""
        for va, vs, ra, rs, _n in self.secs:
            if va <= rva < va + max(vs, rs) and ra + (rva - va) < ra + rs:
                return ra + (rva - va)
        return None

    def o2r(self, off: int):
        """RVA of file offset `off`, None outside every section."""
        for va, _vs, ra, rs, _n in self.secs:
            if ra <= off < ra + rs:
                return va + (off - ra)
        return None

    def text(self):
        """(rva, bytes) of the big code section."""
        tva, _, tra, trs, _ = [s for s in self.secs if s[4] == '.text' and s[3] > 0x1000000][0]
        return tva, self.data[tra:tra + trs]


def find_names(img: Image, pattern: str, needle: str) -> dict:
    """rva -> name for every NUL-terminated string matching `pattern` and containing `needle`."""
    names = {}
    for m in re.finditer((r'(?<![ -~])(' + pattern + r')\x00').encode(), img.data):
        s = m.group(1).decode('latin1')
        rva = img.o2r(m.start(1))
        if needle in s and rva is not None:
            names[rva] = s
    return names


def rel32_hits(img: Image, wanted: set) -> dict:
    """target rva -> [rva of each rel32 in .text that lands on it]."""
    tva, code = img.text()
    want = np.fromiter(wanted, dtype=np.int64)
    hits = {}
    for k in range(4):
        disp = np.frombuffer(code, dtype='<i4', count=(len(code) - k) // 4, offset=k)
        offs = k + 4 * np.arange(len(disp), dtype=np.int64)
        tgt = tva + offs + 4 + disp
        for i in np.nonzero(np.isin(tgt, want))[0]:
            hits.setdefault(int(tgt[i]), []).append(tva + int(offs[i]))
    return hits


def thunk_default(img: Image, md, reloc: int):
    """(value, kind, thunk rva) of the initializer thunk around `reloc`."""
    start = next((reloc - b for b in range(4, 0x30)
                  if img.r2o(reloc - b) is not None
                  and img.data[img.r2o(reloc - b):img.r2o(reloc - b) + 4] == b'\x48\x83\xec\x28'),
                 None)
    if start is None:
        return None, 'no-thunk', reloc
    val, kind = None, '?'
    o = img.r2o(start)
    for ins in md.disasm(img.data[o:o + 0x60], start):
        ops = ins.op_str
        if ins.mnemonic in ('movss', 'movsd') and ops.startswith('xmm2') and 'rip' in ops:
            disp = int(ops.split('rip + ')[1].rstrip(']'), 16)
            val, kind = struct.unpack_from('<f', img.data, img.r2o(ins.address + ins.size + disp))[0], 'float'
        elif ins.mnemonic == 'mov' and re.match(r'r8[db]?, 0x', ops):
            val, kind = int(ops.split(',')[1].strip(), 16), 'int'
        elif ins.mnemonic == 'xor' and re.match(r'r8[db]?, r8[db]?', ops):
            val, kind = 0, 'int'
        if ins.mnemonic == 'call':
            break
    return val, kind, start


def static_defaults(img: Image, rva: int) -> list:
    """[(value, kind, object rva)] for static {vtable, value, name*} Setting objects naming `rva`."""
    out = []
    needle = struct.pack('<Q', img.image_base + rva)
    pos = img.data.find(needle)
    while pos != -1:
        raw = img.data[pos - 8:pos - 4]
        out.append((struct.unpack('<f', raw)[0], 'float', img.o2r(pos - 16)))
        pos = img.data.find(needle, pos + 8)
    return out


def main():
    """Print each matching setting's compiled-in default."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default=DEFAULT_EXE)
    ap.add_argument('--filter', default='', help='substring of the setting name')
    ap.add_argument('--pattern', default=_INI_NAME,
                    help='regex for the whole name (default: INI "Name:Section")')
    a = ap.parse_args()
    img = Image(a.exe)
    names = find_names(img, a.pattern, a.filter)
    if not names:
        sys.exit('no matching setting names')
    hits = rel32_hits(img, set(names))
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    out = [(nm,) + thunk_default(img, md, reloc)
           for rva, nm in names.items() for reloc in hits.get(rva, [])]
    out += [(nm,) + row for rva, nm in names.items() if rva not in hits
            for row in static_defaults(img, rva)]
    for nm, val, kind, addr in sorted(out, key=lambda r: r[0]):
        print('%-64s %-14s %-6s %s' % (nm, val, kind, hex(addr)))


if __name__ == '__main__':
    main()
