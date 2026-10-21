"""
experimental_block_read_test.py — READ-ONLY investigation script.

NOT part of the production collector. Does not import from, or get
imported by, proserver_collector.py. Safe to delete once the
investigation is done.

Purpose
-------
Investigate whether ProEasyDotNet's confirmed ReadDeviceFloat() block-read
API can retrieve temperature (D00207), pressure (D01330) and pH (D02400)
from a single contiguous Float block, as an alternative to the current
three separate ReadSymbolVariant() calls (~1.3s apart on the industrial PC).

Confirmed signature (from --inspect on the industrial PC):
    ReadDeviceFloat(String sNodeName, String sDeviceName,
                     Single[]& pwData, Int16 wCount)

ADDRESS ARITHMETIC — computed before any hardware access, decisive on its
own (see report). Floats in D-register PLC memory conventionally occupy
2 consecutive words (standard Mitsubishi/Pro-face convention: D207 means
words 207-208). A block read starting at D00207 places array element i at
word (207 + 2*i). For pressure (D01330) to land on an element boundary,
(1330-207)/2 must be a whole number. It is 561.5 — not a whole number.
Same for pH: (2400-207)/2 = 1096.5 — also not a whole number.

Under that standard convention, neither pressure nor pH can land on a
clean element boundary of a block started at D00207, for ANY choice of
wCount. This script empirically checks that conclusion (Step 1) before
still running the full investigation exactly as requested, including the
literal full-span block-read attempt and the 5x timing comparison.

This script NEVER calls a Write* method. It does not modify
collector_config.json, proserver_collector.py, the backend, the frontend,
Excel, or PLC memory.

Run on the industrial PC, using the existing venv32 environment:
    set PYTHONNET_RUNTIME=netfx
    venv32\\Scripts\\python.exe experimental_block_read_test.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Must be set BEFORE pythonnet imports any CLR module.
os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")

CONFIG_FILE = Path(__file__).parent / "collector_config.json"


# ── Logging ──────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(tag: str, msg: str) -> None:
    print(f"[{ts()}] [{tag}] {msg}", flush=True)


def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def word_num(address: str) -> int:
    """'D00207' -> 207"""
    return int(address.lstrip("Dd"))


# ── Standalone, read-only ProEasy session (deliberately not shared with the
#    production ProEasySession in proserver_collector.py) ────────────────────

class ReadOnlySession:
    ASSEMBLY_CLASS = "ProEasyDotNet.ProEasy"
    EASY_OBJ_CLASS = "ProEasyDotNet.EasyObject"

    def __init__(self, dll_path: str) -> None:
        import clr  # noqa: F401  (pythonnet)
        from System.Reflection import Assembly
        import System
        self._System = System

        dll = Path(dll_path)
        log("DLL", f"Path   : {dll}")
        log("DLL", f"Exists : {dll.exists()}")
        if not dll.exists():
            raise FileNotFoundError(f"Not found: {dll}")

        self._asm = Assembly.LoadFrom(str(dll))
        asm_name = self._asm.GetName()
        log("DLL", f"Loaded : {asm_name.Name}  v{asm_name.Version}")

        pe_type = self._asm.GetType(self.ASSEMBLY_CLASS)
        if pe_type is None:
            raise RuntimeError(f"{self.ASSEMBLY_CLASS} not found in assembly")
        self._eo_type = self._asm.GetType(self.EASY_OBJ_CLASS)

        self._pe = System.Activator.CreateInstance(pe_type)
        log("PROEASY", "Instance created")

    def init(self) -> None:
        ret = self._pe.EasyInit()
        log("PROEASY", f"EasyInit() returned: {ret!r}")
        if ret != 0:
            raise RuntimeError(f"EasyInit() failed, code={ret}")

    def term(self) -> None:
        try:
            ret = self._pe.EasyTerm()
            log("PROEASY", f"EasyTerm() returned: {ret!r}")
        except Exception as e:
            log("PROEASY", f"EasyTerm() exception (ignored): {e}")

    def _unpack(self, result, fallback_obj):
        if isinstance(result, (tuple, list)):
            ret_code = int(result[0]) if len(result) > 0 else -1
            ret_obj = result[1] if len(result) > 1 else fallback_obj
        else:
            ret_code = int(result) if result is not None else -1
            ret_obj = fallback_obj
        return ret_code, ret_obj

    # ---- READ-ONLY: ReadSymbolVariant (current production method) ---------
    def read_symbol(self, node: str, symbol: str) -> float | None:
        easy_obj = self._System.Activator.CreateInstance(self._eo_type)
        result = self._pe.ReadSymbolVariant(node, symbol, easy_obj)
        ret_code, ret_obj = self._unpack(result, easy_obj)
        if ret_code != 0:
            return None
        return self._extract_float(ret_obj)

    # ---- READ-ONLY: ReadDeviceFloat block read (confirmed signature) ------
    def read_device_float_block(self, node: str, start_address: str, count: int) -> list[float]:
        """
        ReadDeviceFloat(sNodeName, sDeviceName, ref Single[] pwData, wCount)
        Confirmed signature from --inspect on the industrial PC.
        Read-only. Raises on failure; never writes.
        """
        from System import Array, Single
        buf = Array[Single](count)
        result = self._pe.ReadDeviceFloat(node, start_address, buf, count)
        ret_code, ret_buf = self._unpack(result, buf)
        if ret_code != 0:
            raise RuntimeError(f"ReadDeviceFloat failed, code={ret_code}, count={count}")
        return [float(x) for x in ret_buf]

    def _extract_float(self, obj) -> float | None:
        for name in ("GetObject", "GetArray", "GetStringData"):
            fn = getattr(obj, name, None)
            if fn is None:
                continue
            try:
                v = fn()
                if v is None:
                    continue
                if hasattr(v, "Length"):
                    if v.Length == 0:
                        continue
                    return float(v[0])
                return float(v)
            except Exception:
                continue
        return None


# ── Step 2: escalate wCount to find the practical maximum ────────────────────

def find_max_block_count(session: ReadOnlySession, node: str, start_address: str) -> int:
    """
    Escalate wCount until ReadDeviceFloat fails, to find the practical
    maximum block size Pro-Server EX services in one call. Stops at the
    FIRST failure — never retries past it. Purely read-only throughout.
    """
    candidates = [1, 2, 5, 10, 50, 100, 250, 500, 750, 1000, 1098, 1500, 2000]
    last_good = 0
    for n in candidates:
        try:
            t0 = time.perf_counter()
            session.read_device_float_block(node, start_address, n)
            dt = time.perf_counter() - t0
            log("MAXPROBE", f"count={n:<5} OK    ({dt * 1000:.1f} ms)")
            last_good = n
        except Exception as e:
            log("MAXPROBE", f"count={n:<5} FAILED  {e}")
            break
    return last_good


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 70)
    print("  EXPERIMENTAL BLOCK-READ INVESTIGATION (READ-ONLY)")
    print("=" * 70)
    print()

    cfg = load_config()
    node = cfg.get("node", "GP4000_1")
    dll_path = cfg["dll_path"]
    symbols = cfg["readings"]  # {field: {symbol, address, type}}

    addr = {f: c["address"] for f, c in symbols.items()}
    sym = {f: c.get("symbol", f) for f, c in symbols.items()}
    log("CFG", f"node={node}  addresses={addr}  symbols={sym}")

    # ── Address arithmetic check (pure math — no hardware needed) ──────────
    print()
    print("-" * 70)
    print("  ADDRESS ARITHMETIC CHECK (2-word-per-float convention)")
    print("-" * 70)

    w_temp = word_num(addr["temperature"])
    w_pres = word_num(addr["pressure"])
    w_ph = word_num(addr["ph"])

    for label, w in (("temperature", w_temp), ("pressure", w_pres), ("ph", w_ph)):
        offset = w - w_temp
        idx = offset / 2
        aligned = (offset % 2 == 0)
        print(
            f"  {label:<12} word={w:<6} offset_from_start={offset:<6} "
            f"index={idx:<8} "
            f"{'ALIGNED' if aligned else 'MISALIGNED <-- cannot be a clean array element'}"
        )

    span_words = (max(w_temp, w_pres, w_ph) - w_temp) + 2  # +2 covers both words of the last float
    needed_count = math.ceil(span_words / 2)
    print()
    print(f"  Total word span D{w_temp:05d}..D{w_temp + span_words - 1:05d} = {span_words} words")
    print(f"  Floats needed to span that range (2 words each) = {needed_count}")
    print(f"  Bytes for that block (Single = 4 bytes) = {needed_count * 4:,}")
    print()

    session = ReadOnlySession(dll_path)
    session.init()

    try:
        # ── Step 1: confirm actual element stride with a tiny block read ───
        print()
        print("-" * 70)
        print("  STEP 1 — confirm real element stride (read 3 floats from D00207)")
        print("-" * 70)
        try:
            probe = session.read_device_float_block(node, addr["temperature"], 3)
            log("STRIDE", f"3-float block starting at {addr['temperature']}: {probe}")
            log("STRIDE", "Compare probe[0] to the known temperature value from Step 4 below.")
        except Exception as e:
            log("STRIDE", f"block read of 3 failed: {e}")

        # ── Step 2: find practical maximum wCount ──────────────────────────
        print()
        print("-" * 70)
        print("  STEP 2 — escalating wCount to find practical maximum")
        print("-" * 70)
        max_ok = find_max_block_count(session, node, addr["temperature"])
        log("MAXPROBE", f"largest wCount that succeeded: {max_ok}")

        # ── Step 3: attempt the literal full-span block read ───────────────
        print()
        print("-" * 70)
        print(f"  STEP 3 — literal full-span block read (wCount={needed_count})")
        print("-" * 70)
        full_block_supported = needed_count <= max_ok
        if not full_block_supported:
            log("BLOCK", f"SKIPPED — needed count {needed_count} exceeds observed max {max_ok}")
        else:
            try:
                t0 = time.perf_counter()
                full_block = session.read_device_float_block(node, addr["temperature"], needed_count)
                dt = time.perf_counter() - t0
                log("BLOCK", f"full block read OK in {dt * 1000:.1f} ms, {len(full_block)} floats returned")
            except Exception as e:
                log("BLOCK", f"full block read FAILED: {e}")
                full_block_supported = False

        # ── Step 4: 5x comparison ───────────────────────────────────────────
        print()
        print("-" * 70)
        print("  STEP 4 — 5x comparison: block-read vs sequential ReadSymbolVariant")
        print("-" * 70)

        idx_p_floor = (w_pres - w_temp) // 2
        idx_p_ceil = idx_p_floor + 1
        idx_ph_floor = (w_ph - w_temp) // 2
        idx_ph_ceil = idx_ph_floor + 1
        log("BLOCK", f"pressure straddles indices {idx_p_floor}/{idx_p_ceil} — neither is guaranteed correct")
        log("BLOCK", f"pH straddles indices {idx_ph_floor}/{idx_ph_ceil} — neither is guaranteed correct")

        results = []
        for i in range(1, 6):
            row: dict = {"iter": i}

            # -- sequential ReadSymbolVariant (current production method) --
            t0 = time.perf_counter()
            t_sym = session.read_symbol(node, sym["temperature"])
            p_sym = session.read_symbol(node, sym["pressure"])
            ph_sym = session.read_symbol(node, sym["ph"])
            t_seq = time.perf_counter() - t0
            row.update(seq_time=t_seq, seq_temp=t_sym, seq_pres=p_sym, seq_ph=ph_sym)

            # -- block read attempt (only if the full span is supported) --
            if full_block_supported:
                try:
                    t0 = time.perf_counter()
                    blk = session.read_device_float_block(node, addr["temperature"], needed_count)
                    t_blk = time.perf_counter() - t0
                    row.update(
                        blk_time=t_blk,
                        blk_temp=blk[0] if len(blk) > 0 else None,
                        blk_pres_floor=blk[idx_p_floor] if idx_p_floor < len(blk) else None,
                        blk_pres_ceil=blk[idx_p_ceil] if idx_p_ceil < len(blk) else None,
                        blk_ph_floor=blk[idx_ph_floor] if idx_ph_floor < len(blk) else None,
                        blk_ph_ceil=blk[idx_ph_ceil] if idx_ph_ceil < len(blk) else None,
                    )
                except Exception as e:
                    row.update(blk_time=None, blk_error=str(e))
            else:
                row.update(blk_time=None)

            results.append(row)
            log(
                "ITER",
                f"#{i}  seq={t_seq * 1000:.1f}ms  T={t_sym} P={p_sym} pH={ph_sym}"
                + (
                    f"   |  blk={row['blk_time'] * 1000:.1f}ms  T={row.get('blk_temp')}  "
                    f"P[floor/ceil]={row.get('blk_pres_floor')}/{row.get('blk_pres_ceil')}  "
                    f"pH[floor/ceil]={row.get('blk_ph_floor')}/{row.get('blk_ph_ceil')}"
                    if row.get("blk_time") is not None
                    else "   |  blk=SKIPPED/FAILED"
                ),
            )
            time.sleep(1)

        # ── Final report ─────────────────────────────────────────────────
        print()
        print("=" * 70)
        print("  FINAL REPORT")
        print("=" * 70)
        print(
            f"  Address arithmetic : pressure index={(w_pres - w_temp) / 2}  "
            f"({'ALIGNED' if (w_pres - w_temp) % 2 == 0 else 'MISALIGNED'})"
        )
        print(
            f"                       pH index={(w_ph - w_temp) / 2}  "
            f"({'ALIGNED' if (w_ph - w_temp) % 2 == 0 else 'MISALIGNED'})"
        )
        print(f"  Max supported wCount observed : {max_ok}")
        print(
            f"  Full-span count needed        : {needed_count}  "
            f"({'SUPPORTED' if full_block_supported else 'EXCEEDS MAX -- not attempted/failed'})"
        )
        print()
        print(f"  {'iter':<5}{'seq_ms':<9}{'blk_ms':<9}{'seq_T':<10}{'blk_T':<10}"
              f"{'seq_P':<12}{'blk_P(floor/ceil)':<24}{'seq_pH':<10}{'blk_pH(floor/ceil)':<20}")
        for r in results:
            blk_ms = f"{r['blk_time'] * 1000:.1f}" if r.get("blk_time") is not None else "N/A"
            blk_t = str(r.get("blk_temp", "N/A"))
            blk_p = f"{r.get('blk_pres_floor', 'N/A')}/{r.get('blk_pres_ceil', 'N/A')}"
            blk_ph = f"{r.get('blk_ph_floor', 'N/A')}/{r.get('blk_ph_ceil', 'N/A')}"
            print(
                f"  {r['iter']:<5}{r['seq_time'] * 1000:<9.1f}{blk_ms:<9}"
                f"{str(r['seq_temp']):<10}{blk_t:<10}"
                f"{str(r['seq_pres']):<12}{blk_p:<24}"
                f"{str(r['seq_ph']):<10}{blk_ph:<20}"
            )

        avg_seq = sum(r["seq_time"] for r in results) / len(results)
        blk_times = [r["blk_time"] for r in results if r.get("blk_time") is not None]
        print()
        print(f"  Average sequential (3x ReadSymbolVariant) time : {avg_seq * 1000:.1f} ms")
        if blk_times:
            avg_blk = sum(blk_times) / len(blk_times)
            print(f"  Average block-read (ReadDeviceFloat) time      : {avg_blk * 1000:.1f} ms")
        else:
            print("  Average block-read (ReadDeviceFloat) time      : N/A (not supported/failed)")
        print()
        print("  No PLC values, Pro-Server config, Excel, collector, backend or")
        print("  frontend were modified by this script.")

    finally:
        session.term()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
