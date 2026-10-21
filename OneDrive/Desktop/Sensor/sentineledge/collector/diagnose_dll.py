"""
diagnose_dll.py — One-shot compatibility diagnostic for ProEasyDotNet.dll.

Run on the industrial PC:
    python diagnose_dll.py

No installs required beyond what is already present.
Does NOT modify any files, registry, or Pro-Server EX configuration.
"""

import platform
import struct
import sys
from pathlib import Path

DLLS = [
    r"C:\Program Files (x86)\Pro-face\Pro-Server EX\PRO-SDK\DotNet\bin\ProEasyDotNet.dll",
    r"C:\Program Files (x86)\Pro-face\Pro-Server EX\PRO-SDK\DotNet20\bin\ProEasyDotNet.dll",
    r"C:\Program Files (x86)\Pro-face\Pro-Server EX\PRO-SDK\DotNet40\bin\ProEasyDotNet.dll",
]

# ── PE / CorFlags reader ───────────────────────────────────────────────────────

MACHINE = {
    0x0000: "AnyCPU (native)",
    0x014c: "x86 (32-bit)",
    0x8664: "x64 (64-bit)",
    0x01c4: "ARM",
    0xaa64: "ARM64",
}

CORFLAGS = {
    0x01: "ILONLY",
    0x02: "32BITREQUIRED",
    0x08: "32BITPREFERRED",
    0x10: "STRONGNAMESIGNED",
}


def read_pe_info(path: Path) -> dict:
    """
    Read PE header + optional .NET CLR header from a DLL.
    Returns a dict with machine, bitness, is_managed, cor_flags, cor_flags_detail.
    """
    info = {
        "exists":           path.exists(),
        "size_bytes":       None,
        "machine_code":     None,
        "machine":          "unknown",
        "is_managed":       False,
        "cor_flags":        None,
        "cor_flags_detail": [],
        "error":            None,
    }
    if not path.exists():
        return info

    try:
        info["size_bytes"] = path.stat().st_size

        with open(path, "rb") as f:
            # MZ header
            mz = f.read(2)
            if mz != b"MZ":
                info["error"] = "Not a PE file (no MZ header)"
                return info

            # e_lfanew at offset 0x3C
            f.seek(0x3C)
            (e_lfanew,) = struct.unpack("<I", f.read(4))

            # PE signature
            f.seek(e_lfanew)
            pe_sig = f.read(4)
            if pe_sig != b"PE\x00\x00":
                info["error"] = f"No PE signature at 0x{e_lfanew:X}"
                return info

            # COFF header: Machine (2 bytes)
            (machine,) = struct.unpack("<H", f.read(2))
            info["machine_code"] = machine
            info["machine"]      = MACHINE.get(machine, f"unknown (0x{machine:04X})")

            # Number of sections, timestamp, symbol table ptr, num symbols
            f.read(2 + 4 + 4 + 4)

            # SizeOfOptionalHeader
            (opt_size,) = struct.unpack("<H", f.read(2))
            # Characteristics
            f.read(2)

            if opt_size == 0:
                return info

            # Optional header magic: 0x10b=PE32, 0x20b=PE32+
            opt_start = f.tell()
            (magic,) = struct.unpack("<H", f.read(2))
            is_pe32plus = (magic == 0x20b)

            # For PE32:  data directories start at opt_start + 96
            # For PE32+: data directories start at opt_start + 112
            dd_offset = opt_start + (112 if is_pe32plus else 96)
            f.seek(dd_offset)

            # Data directory 14 (index 13) = COM descriptor (.NET)
            # Each entry is 8 bytes (RVA + size)
            # We need entry index 14 (0-based index 14)
            # But standard: directory[14] = COM Runtime Descriptor
            # Actually it's index 14 in the array = offset 14*8 = 112 bytes from dd start

            # Read all 16 standard directories (16 * 8 = 128 bytes)
            dirs = []
            for _ in range(16):
                rva, size = struct.unpack("<II", f.read(8))
                dirs.append((rva, size))

            # Index 14 = COM descriptor
            if len(dirs) > 14:
                com_rva, com_size = dirs[14]
                if com_rva != 0 and com_size >= 72:
                    info["is_managed"] = True

                    # To read CorFlags we need to walk sections to convert RVA → file offset.
                    # Reset to section headers.
                    # Section headers start right after optional header.
                    sec_start = opt_start + opt_size
                    f.seek(sec_start)

                    # Number of sections was read above — re-read from COFF
                    f.seek(e_lfanew + 4 + 2)
                    (num_sections,) = struct.unpack("<H", f.read(2))
                    f.seek(sec_start)

                    sections = []
                    for _ in range(num_sections):
                        name   = f.read(8)
                        vsize, = struct.unpack("<I", f.read(4))
                        vadr,  = struct.unpack("<I", f.read(4))
                        rsize, = struct.unpack("<I", f.read(4))
                        radr,  = struct.unpack("<I", f.read(4))
                        f.read(16)  # remainder
                        sections.append((vadr, vsize, radr, rsize))

                    def rva_to_offset(rva):
                        for vadr, vsize, radr, rsize in sections:
                            if vadr <= rva < vadr + max(vsize, rsize):
                                return radr + (rva - vadr)
                        return None

                    com_offset = rva_to_offset(com_rva)
                    if com_offset is not None:
                        f.seek(com_offset)
                        # CLI header layout (72 bytes):
                        #  0: cb (4)
                        #  4: MajorRuntimeVersion (2)
                        #  6: MinorRuntimeVersion (2)
                        #  8: MetaData RVA+Size (8)
                        # 16: Flags / CorFlags (4)
                        f.read(16)
                        (cor_flags,) = struct.unpack("<I", f.read(4))
                        info["cor_flags"] = cor_flags
                        detail = [name for bit, name in CORFLAGS.items() if cor_flags & bit]
                        info["cor_flags_detail"] = detail if detail else ["(none set)"]

    except Exception as exc:
        info["error"] = str(exc)

    return info


def classify(info: dict) -> str:
    """Human-readable summary of what this DLL can run in."""
    if not info["exists"]:
        return "FILE NOT FOUND"
    if info["error"]:
        return f"READ ERROR: {info['error']}"
    if not info["is_managed"]:
        m = info["machine"]
        return f"Native/unmanaged  [{m}]"

    m    = info["machine"]
    cf   = info["cor_flags"] or 0
    il   = bool(cf & 0x01)
    x86r = bool(cf & 0x02)
    x86p = bool(cf & 0x08)

    if x86r:
        return f"Managed .NET  32-bit required (WILL FAIL in 64-bit Python)  [{m}]"
    if il and not x86r and not x86p:
        return f"Managed .NET  AnyCPU — should load in both 32-bit and 64-bit Python  [{m}]"
    if x86p:
        return f"Managed .NET  AnyCPU prefer-32-bit — loads in 64-bit but prefers 32  [{m}]"
    return f"Managed .NET  [{m}]  CorFlags=0x{cf:04X}"


# ── main ───────────────────────────────────────────────────────────────────────

print()
print("=" * 70)
print("  PYTHON ENVIRONMENT")
print("=" * 70)
print(f"  Python version     : {sys.version}")
print(f"  platform.arch      : {platform.architecture()}")
print(f"  pointer size (bits): {struct.calcsize('P') * 8}")
print(f"  executable         : {sys.executable}")

# pythonnet
try:
    from importlib.metadata import version as _pkg_version
    print(f"  pythonnet version  : {_pkg_version('pythonnet')}")
except Exception as e:
    print(f"  pythonnet version  : could not determine ({e})")

# which .NET runtime pythonnet is using
try:
    import clr
    print(f"  clr module         : {clr.__file__ if hasattr(clr, '__file__') else 'loaded'}")
    try:
        import System
        print(f"  .NET runtime       : {System.Environment.Version}")
    except Exception as e:
        print(f"  .NET runtime       : could not determine ({e})")
except ImportError:
    print("  clr                : NOT AVAILABLE (pythonnet not installed)")

print()
print("=" * 70)
print("  DLL ANALYSIS")
print("=" * 70)

for dll_str in DLLS:
    p = Path(dll_str)
    print(f"\n  {p.name}  ({p.parent})")
    info = read_pe_info(p)
    print(f"    exists      : {info['exists']}")
    if info["exists"]:
        print(f"    size        : {info['size_bytes']:,} bytes")
        print(f"    machine     : {info['machine']}")
        print(f"    managed     : {info['is_managed']}")
        if info["is_managed"] and info["cor_flags"] is not None:
            print(f"    CorFlags    : 0x{info['cor_flags']:04X}  {info['cor_flags_detail']}")
        if info["error"]:
            print(f"    error       : {info['error']}")
        print(f"    VERDICT     : {classify(info)}")

print()
print("=" * 70)
print("  COMPATIBILITY SUMMARY")
print("=" * 70)
py_bits = struct.calcsize("P") * 8
print(f"  Python is {py_bits}-bit")
print()
print("  To load a DLL in this Python process it must be one of:")
if py_bits == 64:
    print("    - Managed AnyCPU (no 32BITREQUIRED flag)")
    print("    - Managed x64")
    print("    - Native x64")
    print()
    print("  A DLL with 32BITREQUIRED=True OR a native x86 DLL CANNOT load here.")
    print("  BadImageFormatException = one of those cases.")
    print()
    print("  Fix options (in order of preference):")
    print("    1. Use 32-bit Python 3.x  (safest — Pro-Server EX SDK is 32-bit)")
    print("    2. Use pythonnet with 'set PYTHONNET_RUNTIME=netfx' + check CorFlags")
else:
    print("    - Managed AnyCPU or 32-bit required")
    print("    - Native x86")

print()
