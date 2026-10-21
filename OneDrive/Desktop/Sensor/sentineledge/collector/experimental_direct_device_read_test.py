"""
experimental_direct_device_read_test.py — READ-ONLY investigation script.

NOT part of the production collector. New, standalone file. Does not
import from, or modify, proserver_collector.py, collector_config.json,
the backend, the frontend, Excel, or PLC/Pro-Server configuration.

Purpose
-------
Follow-up to experimental_block_read_test.py. The block-read approach was
already ruled out by address arithmetic and confirmed on hardware:
element 0 of a ReadDeviceFloat(D00207, count=3) block matched temperature,
but elements 1-2 were garbage, because pressure (D01330) and pH (D02400)
are not valid element boundaries of an array started at D00207.

This experiment instead measures direct, single-address reads:

    ReadDeviceFloat("GP4000_1", "D00207", pwData, 1)   # temperature
    ReadDeviceFloat("GP4000_1", "D01330", pwData, 1)   # pressure
    ReadDeviceFloat("GP4000_1", "D02400", pwData, 1)   # pH

run sequentially in that order, 5 complete cycles, with per-call
before/after timestamps, elapsed ms, returned value, and return code.

This script deliberately does NOT call ReadSymbolVariant (excluded from
this experiment by design) and therefore never touches
ProEasyDotNet.EasyObject at all. ReadDeviceFloat takes only a Single[]
array as its data parameter — no EasyObject involved — so the
ArgumentNullException that crashed experimental_block_read_test.py's
Step 4 cannot occur here.

Root cause of that earlier crash, for the record (a bug in that
experimental script, not a DLL/PLC problem): production's
ProEasySession.read_symbol() in proserver_collector.py guards EasyObject
creation --

    if self._eo_type is not None:
        try: easy_obj = Activator.CreateInstance(self._eo_type)
        except Exception: pass
    ... falls back to ReadSymbolVariant(node, symbol) with no ref param
        if easy_obj is still None.

experimental_block_read_test.py's simplified read_symbol() dropped that
guard and called Activator.CreateInstance(self._eo_type) unconditionally,
which threw when GetType("ProEasyDotNet.EasyObject") returned None in
that process. This script has no read_symbol() method at all, so there
is nothing to fix here.

SECOND experiment in this file (clearly separated, still read-only):
whether a second, independent ProEasy instance can be EasyInit()'d while
the first is still active, and whether reads from two instances can
safely coexist / overlap in time. Investigation only — this does NOT
wire anything parallel into production.

Run on the industrial PC, using the existing venv32 environment:
    set PYTHONNET_RUNTIME=netfx
    venv32\\Scripts\\python.exe experimental_direct_device_read_test.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
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


# ── Minimal, standalone ProEasy session — ReadDeviceFloat(count=1) only ──────

class DeviceFloatSession:
    """
    Only implements EasyInit / EasyTerm / ReadDeviceFloat(count=1).
    Deliberately has NO read_symbol()/ReadSymbolVariant method and never
    looks up ProEasyDotNet.EasyObject — that type is not needed for this
    call shape, so the earlier script's crash class cannot occur here.
    """

    ASSEMBLY_CLASS = "ProEasyDotNet.ProEasy"

    def __init__(self, dll_path: str, label: str = "A") -> None:
        import clr  # noqa: F401  (pythonnet)
        from System.Reflection import Assembly
        import System
        self._System = System
        self.label = label

        dll = Path(dll_path)
        if not dll.exists():
            raise FileNotFoundError(f"Not found: {dll}")

        self._asm = Assembly.LoadFrom(str(dll))
        pe_type = self._asm.GetType(self.ASSEMBLY_CLASS)
        if pe_type is None:
            raise RuntimeError(f"{self.ASSEMBLY_CLASS} not found in assembly")
        self._pe = System.Activator.CreateInstance(pe_type)

    def init(self) -> int:
        ret = self._pe.EasyInit()
        log("PROEASY", f"[{self.label}] EasyInit() returned: {ret!r}")
        return int(ret)

    def term(self) -> None:
        try:
            ret = self._pe.EasyTerm()
            log("PROEASY", f"[{self.label}] EasyTerm() returned: {ret!r}")
        except Exception as e:
            log("PROEASY", f"[{self.label}] EasyTerm() exception (ignored): {e}")

    def read_device_float_1(self, node: str, address: str):
        """
        ReadDeviceFloat(sNodeName, sDeviceName, ref Single[] pwData, wCount=1)
        Confirmed signature and array-creation pattern — already exercised
        successfully on hardware by experimental_block_read_test.py
        (counts 1..500 all succeeded there).
        Read-only. Never writes. Returns (return_code, value_or_None).
        """
        from System import Array, Single
        buf = Array[Single](1)
        result = self._pe.ReadDeviceFloat(node, address, buf, 1)

        if isinstance(result, (tuple, list)):
            ret_code = int(result[0]) if len(result) > 0 else -1
            ret_buf = result[1] if len(result) > 1 else buf
        else:
            ret_code = int(result) if result is not None else -1
            ret_buf = buf

        if ret_code != 0:
            return ret_code, None
        try:
            value = float(ret_buf[0])
        except Exception:
            value = None
        return ret_code, value


# ── Experiment 1: sequential direct reads, 5 cycles ──────────────────────────

def run_sequential_experiment(session: DeviceFloatSession, node: str, addr: dict) -> list[dict]:
    print()
    print("=" * 70)
    print("  EXPERIMENT 1 — sequential ReadDeviceFloat(count=1), 5 cycles")
    print("=" * 70)

    order = [("T", "temperature"), ("P", "pressure"), ("pH", "ph")]
    cycles = []

    for c in range(1, 6):
        print(f"\nCycle {c}")
        cycle_rows = {}
        cycle_t0 = time.perf_counter()

        for short, field in order:
            address = addr[field]
            t_before = datetime.now()
            p0 = time.perf_counter()
            error = None
            try:
                ret_code, value = session.read_device_float_1(node, address)
            except Exception as e:
                ret_code, value, error = None, None, str(e)
            p1 = time.perf_counter()
            t_after = datetime.now()
            elapsed_ms = (p1 - p0) * 1000

            cycle_rows[field] = dict(
                short=short, address=address,
                t_before=t_before, t_after=t_after,
                elapsed_ms=elapsed_ms, value=value,
                ret_code=ret_code, error=error,
            )
            val_str = f"{value:.5f}" if value is not None else f"FAILED(code={ret_code}, err={error})"
            print(
                f"  {short:<4}{address} = {val_str:<26} {elapsed_ms:>8.1f} ms   "
                f"[{t_before.strftime('%H:%M:%S.%f')[:-3]} -> {t_after.strftime('%H:%M:%S.%f')[:-3]}]"
            )

        cycle_total_ms = (time.perf_counter() - cycle_t0) * 1000
        print(f"  Total = {cycle_total_ms:.1f} ms")
        cycles.append(dict(rows=cycle_rows, total_ms=cycle_total_ms))

    return cycles


# ── Experiment 2: dual-instance coexistence + concurrency ───────────────────

def run_dual_instance_experiment(dll_path: str, node: str, addr: dict) -> None:
    print()
    print("=" * 70)
    print("  EXPERIMENT 2 — can two independent ProEasy instances coexist?")
    print("=" * 70)
    print("  (investigation only — nothing here is wired into production;")
    print("   this does NOT introduce parallel reads into the collector)")

    # -- Part A: create + init two SEPARATE instances sequentially ----------
    print("\n-- Part A: sequential dual-instance init --")
    session_a = DeviceFloatSession(dll_path, label="A")
    ret_a = session_a.init()
    if ret_a != 0:
        log("DUAL", f"Instance A EasyInit() failed with code {ret_a} -- aborting dual-instance test")
        return

    session_b = None
    ret_b = None
    try:
        session_b = DeviceFloatSession(dll_path, label="B")
        ret_b = session_b.init()
    except Exception as e:
        log("DUAL", f"Instance B creation/init raised: {e}")

    if ret_b != 0:
        log(
            "DUAL",
            f"Instance B EasyInit() while A is active -> code={ret_b!r} "
            "(non-zero/None suggests the SDK may enforce a single active session; "
            "treat concurrent instances as UNSAFE until proven otherwise)",
        )
        session_a.term()
        return

    log("DUAL", "Both instance A and instance B initialised successfully — sequential coexistence appears possible")

    # -- Part B: sequential reads from both, interleaved --------------------
    print("\n-- Part B: interleaved sequential reads, A then B, 3 rounds --")
    for i in range(1, 4):
        ra, va = session_a.read_device_float_1(node, addr["temperature"])
        rb, vb = session_b.read_device_float_1(node, addr["temperature"])
        log("DUAL", f"round {i}: A.temp code={ra} val={va}   B.temp code={rb} val={vb}")

    # -- Part C: genuine concurrent threads, overlapping in time --------------
    print("\n-- Part C: concurrent threads, A and B reading at the same time --")
    results: dict[str, list] = {"A": [], "B": []}
    errors: dict[str, list] = {"A": [], "B": []}

    def worker(sess: DeviceFloatSession, key: str, field: str, n: int = 5) -> None:
        for _ in range(n):
            try:
                t0 = time.perf_counter()
                code, val = sess.read_device_float_1(node, addr[field])
                dt = (time.perf_counter() - t0) * 1000
                results[key].append((code, val, round(dt, 1)))
            except Exception as e:
                errors[key].append(str(e))

    th_a = threading.Thread(target=worker, args=(session_a, "A", "temperature"), daemon=True)
    th_b = threading.Thread(target=worker, args=(session_b, "B", "pressure"), daemon=True)

    t_start = time.perf_counter()
    th_a.start()
    th_b.start()
    th_a.join(timeout=30)
    th_b.join(timeout=30)
    t_total = (time.perf_counter() - t_start) * 1000

    if th_a.is_alive() or th_b.is_alive():
        log(
            "DUAL",
            "WARNING: at least one thread did not finish within 30s -- possible "
            "hang/deadlock under concurrent access. Treat concurrent reads as "
            "UNSAFE until proven otherwise.",
        )
    else:
        log("DUAL", f"Both threads completed in {t_total:.1f} ms wall-clock")
        log("DUAL", f"  A (temperature) results: {results['A']}")
        log("DUAL", f"  A errors: {errors['A'] or 'none'}")
        log("DUAL", f"  B (pressure)    results: {results['B']}")
        log("DUAL", f"  B errors: {errors['B'] or 'none'}")

        a_ok = bool(results["A"]) and all(code == 0 for code, _, _ in results["A"]) and not errors["A"]
        b_ok = bool(results["B"]) and all(code == 0 for code, _, _ in results["B"]) and not errors["B"]
        if a_ok and b_ok:
            log(
                "DUAL",
                "CONCLUSION: both instances completed concurrent reads without "
                "exceptions or error codes in this short test. This is a "
                "preliminary favourable signal only -- it does NOT prove full "
                "thread-safety under sustained production load.",
            )
        else:
            log("DUAL", "CONCLUSION: at least one instance errored during concurrent access -- treat as UNSAFE.")

    session_a.term()
    session_b.term()


# ── Final report ─────────────────────────────────────────────────────────────

def print_final_report(cycles: list[dict]) -> None:
    print()
    print("=" * 70)
    print("  FINAL REPORT")
    print("=" * 70)

    fields = ["temperature", "pressure", "ph"]
    all_ok = True
    for field in fields:
        times = [c["rows"][field]["elapsed_ms"] for c in cycles]
        vals = [c["rows"][field]["value"] for c in cycles]
        codes = [c["rows"][field]["ret_code"] for c in cycles]
        avg = sum(times) / len(times)
        field_ok = all(code == 0 for code in codes) and all(v is not None for v in vals)
        all_ok = all_ok and field_ok
        val_strs = [f"{v:.5f}" if v is not None else "FAIL" for v in vals]
        print(
            f"  {field:<12} avg={avg:8.1f} ms   values={val_strs}   "
            f"codes={codes}   {'OK' if field_ok else 'FAILED AT LEAST ONCE'}"
        )

    total_times = [c["total_ms"] for c in cycles]
    avg_total = sum(total_times) / len(total_times)
    print(f"\n  Average total cycle time (T+P+pH sequential) = {avg_total:.1f} ms")
    print(f"  All three values correct across all 5 cycles: {'YES' if all_ok else 'NO'}")

    print()
    print("  Comparison with existing ReadSymbolVariant approach")
    print("  " + "-" * 53)
    print("  ReadSymbolVariant was NOT called in this script (excluded by the")
    print("  investigation's instructions). This comparison uses already-observed")
    print("  empirical figures, not a fresh call in this run:")
    print("    - Production ReadSymbolVariant calls were originally reported as")
    print("      ~1.3 s apart per symbol on this industrial PC.")
    print("    - The prior block-read experiment measured a single")
    print("      ReadDeviceFloat(D00207, count=1) call at ~1346 ms.")
    print("    - This run's per-address averages are printed above.")
    print("  If those averages sit in the same ~1.3-1.5 s range as the historical")
    print("  ReadSymbolVariant figure, ReadDeviceFloat(count=1) is NOT meaningfully")
    print("  faster per call -- most of the ~1.3s appears to be per-call")
    print("  driver/IPC overhead common to both APIs, not something either avoids.")

    print()
    print("  IMPORTANT: sequential reads, however fast, are NOT a synchronized")
    print("  snapshot. Each value is still read at a different point in time.")
    print("  This script measures timing only -- it draws no conclusion about")
    print("  atomicity or coherence between temperature, pressure and pH.")

    print()
    print("  No PLC values, Pro-Server config, Excel, collector, backend or")
    print("  frontend were modified by this script.")


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 70)
    print("  EXPERIMENTAL DIRECT DEVICE READ TEST (READ-ONLY)")
    print("=" * 70)

    cfg = load_config()
    node = cfg.get("node", "GP4000_1")
    dll_path = cfg["dll_path"]
    symbols = cfg["readings"]
    addr = {f: c["address"] for f, c in symbols.items()}
    log("CFG", f"node={node}  addresses={addr}")

    session = DeviceFloatSession(dll_path, label="MAIN")
    ret = session.init()
    if ret != 0:
        log("PROEASY", f"EasyInit() failed, code={ret} -- aborting")
        sys.exit(1)

    try:
        cycles = run_sequential_experiment(session, node, addr)
        print_final_report(cycles)
    finally:
        session.term()

    # Second, separate experiment — uses its own fresh instances; `session`
    # above has already been terminated and is not reused here.
    try:
        run_dual_instance_experiment(dll_path, node, addr)
    except Exception:
        log("DUAL", "dual-instance experiment raised an unhandled exception:")
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
