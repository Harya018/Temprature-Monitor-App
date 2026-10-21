"""
proserver_collector.py — Pro-Server EX live data collector.

Confirmed environment:
  Machine          : 192.168.250.243 (Pro-Server EX + FastAPI on same PC)
  Backend          : http://localhost:5000
  Python           : 3.12 32-bit (C:\\Python312-32)
  Runtime          : PYTHONNET_RUNTIME=netfx  (.NET Framework)
  Assembly         : ProEasyDotNet v1.34.0.32548
  Class            : ProEasyDotNet.ProEasy
  Node             : GP4000_1
  Symbols          : temperature / pressure / Ph

USAGE
  set PYTHONNET_RUNTIME=netfx
  venv32\\Scripts\\python.exe proserver_collector.py --test
  venv32\\Scripts\\python.exe proserver_collector.py --inspect
  venv32\\Scripts\\python.exe proserver_collector.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Must be set BEFORE pythonnet imports any CLR module.
os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")

import requests  # noqa: E402

CONFIG_FILE = Path(__file__).parent / "collector_config.json"

# ── Runtime cache (Pro-Server EX Cache Buffer Control) ──────────────────────────
# Registers temperature/pressure/Ph into a named runtime cache so ReadSymbolVariant()
# is served from Pro-Server EX's cache instead of a live/direct PLC read on every
# call. In-memory only on the Pro-Server EX process -- does NOT modify the .npxe
# project file. See PS_CreateCache / PS_EntryCacheRecord, Pro-Server EX Reference
# Manual ch.27.3.
CACHE_NAME           = "SentinelEdgeCache"
CACHE_POLLING_MS     = 1000
CACHE_APP_KIND_FLOAT = 10   # wAppKind: 10 = Single-precision floating point

# ── Logging ────────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def log(tag: str, msg: str) -> None:
    print(f"[{ts()}] [{tag}] {msg}", flush=True)

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ── ProEasy session ────────────────────────────────────────────────────────────

class ProEasySession:
    """
    Holds the loaded assembly, ProEasy instance, and EasyObject type so
    that all three are created once and reused across reads.
    """

    ASSEMBLY_CLASS = "ProEasyDotNet.ProEasy"
    EASY_OBJ_CLASS = "ProEasyDotNet.EasyObject"

    def __init__(self, dll_path: str) -> None:
        import clr                               # pythonnet  # noqa: F401
        from System.Reflection import Assembly   # type: ignore
        import System                            # type: ignore

        dll = Path(dll_path)
        log("DLL", f"Path       : {dll}")
        log("DLL", f"Exists     : {dll.exists()}")

        if not dll.exists():
            raise FileNotFoundError(
                f"Not found: {dll}\n"
                r"Find it:  dir /s /b 'C:\Program Files*' | findstr ProEasyDotNet"
            )

        log("DLL", "Assembly.LoadFrom() ...")
        self._asm = Assembly.LoadFrom(str(dll))
        asm_name  = self._asm.GetName()
        log("DLL", f"Loaded     : {asm_name.Name}  v{asm_name.Version}")

        # Get ProEasy type
        pe_type = self._asm.GetType(self.ASSEMBLY_CLASS)
        if pe_type is None:
            types = [t.FullName for t in self._asm.GetExportedTypes()]
            raise RuntimeError(
                f"'{self.ASSEMBLY_CLASS}' not found in assembly.\n"
                f"Exported types: {types}"
            )
        log("DLL", f"Type       : {pe_type.FullName}")

        # Get EasyObject type (needed to create ref-param instances)
        self._eo_type = self._asm.GetType(self.EASY_OBJ_CLASS)
        if self._eo_type is None:
            log("DLL", f"Warning: '{self.EASY_OBJ_CLASS}' type not found — value extraction may be limited")

        # Instantiate ProEasy
        log("PROEASY", "Activator.CreateInstance(ProEasyDotNet.ProEasy) ...")
        self._pe = System.Activator.CreateInstance(pe_type)
        log("PROEASY", "Instance created")

        self._System = System

    # ── Init / Term ────────────────────────────────────────────────────────────

    def init(self) -> int:
        log("PROEASY", "EasyInit() ...")
        ret = self._pe.EasyInit()
        log("PROEASY", f"EasyInit() returned: {ret!r}")
        if ret != 0:
            msg = self._error_message(ret)
            raise RuntimeError(f"EasyInit() failed — code {ret}  {msg}")
        return ret

    def term(self) -> None:
        try:
            ret = self._pe.EasyTerm()
            log("PROEASY", f"EasyTerm() returned: {ret!r}")
        except Exception as e:
            log("PROEASY", f"EasyTerm() exception (ignored): {e}")

    # ── Runtime cache (Pro-Server EX Cache Buffer Control) ────────────────────

    def start_cache(self, node: str, symbols: list[str]) -> None:
        """
        Create the SentinelEdge runtime cache and register each of `symbols`
        into it, then start caching. Subsequent read_symbol() calls for a
        registered symbol are served from this cache (Cache Read) instead of
        triggering a live/direct PLC round-trip.

        In-memory only on the Pro-Server EX process -- does not modify the
        .npxe project file. Call once per new ProEasySession; do not call
        again while the same session's cache is already active.
        """
        log("CACHE", f"PS_CreateCache({CACHE_NAME!r}, {CACHE_POLLING_MS}) ...")
        ret = self._pe.PS_CreateCache(CACHE_NAME, CACHE_POLLING_MS)
        log("CACHE", f"PS_CreateCache() returned: {ret!r}")
        if ret != 0:
            # A hard-killed collector never ran stop_cache(), so a stale cache with
            # our name may still exist in Pro-Server EX. Discard it and retry once.
            log("CACHE", "PS_CreateCache() failed — destroying any stale cache and retrying once")
            try:
                self._pe.PS_DestroyCache(CACHE_NAME)
            except Exception as e:
                log("CACHE", f"  PS_DestroyCache() during recovery raised (ignored): {e}")
            ret = self._pe.PS_CreateCache(CACHE_NAME, CACHE_POLLING_MS)
            log("CACHE", f"PS_CreateCache() retry returned: {ret!r}")
        if ret != 0:
            msg = self._error_message(ret)
            raise RuntimeError(f"PS_CreateCache() failed — code {ret}  {msg}")

        try:
            for symbol in symbols:
                log(
                    "CACHE",
                    f"PS_EntryCacheRecord({CACHE_NAME!r}, {node!r}, {symbol!r}, "
                    f"{CACHE_APP_KIND_FLOAT}, 1) ...",
                )
                ret = self._pe.PS_EntryCacheRecord(
                    CACHE_NAME, node, symbol, CACHE_APP_KIND_FLOAT, 1
                )
                log("CACHE", f"PS_EntryCacheRecord({symbol!r}) returned: {ret!r}")
                if ret != 0:
                    msg = self._error_message(ret)
                    raise RuntimeError(
                        f"PS_EntryCacheRecord({symbol!r}) failed — code {ret}  {msg}"
                    )

            log("CACHE", f"PS_StartCache({CACHE_NAME!r}) ...")
            ret = self._pe.PS_StartCache(CACHE_NAME)
            log("CACHE", f"PS_StartCache() returned: {ret!r}")
            if ret != 0:
                msg = self._error_message(ret)
                raise RuntimeError(f"PS_StartCache() failed — code {ret}  {msg}")

        except Exception:
            log("CACHE", "start_cache() registration/start failed — attempting PS_DestroyCache() cleanup")
            try:
                self._pe.PS_DestroyCache(CACHE_NAME)
            except Exception as cleanup_exc:
                log("CACHE", f"  PS_DestroyCache() cleanup also failed: {cleanup_exc}")
            raise

    def stop_cache(self) -> None:
        """
        Stop and discard the runtime cache. Never raises -- safe to call
        during shutdown or reconnect even if the cache was never started.
        """
        try:
            ret = self._pe.PS_StopCache(CACHE_NAME)
            log("CACHE", f"PS_StopCache() returned: {ret!r}")
        except Exception as e:
            log("CACHE", f"PS_StopCache() exception (ignored): {e}")
        try:
            ret = self._pe.PS_DestroyCache(CACHE_NAME)
            log("CACHE", f"PS_DestroyCache() returned: {ret!r}")
        except Exception as e:
            log("CACHE", f"PS_DestroyCache() exception (ignored): {e}")

    def _error_message(self, code: int) -> str:
        """Try to get a human-readable error message from ProEasy."""
        for method_name in ("EasyLoadErrorMessage", "EasyLoadErrorMessageEx",
                            "GetLastErrorMessage", "GetErrorMessage"):
            fn = getattr(self._pe, method_name, None)
            if fn is not None:
                try:
                    msg = fn(code)
                    return f"({msg})"
                except Exception:
                    pass
        return ""

    # ── ReadSymbolVariant ──────────────────────────────────────────────────────

    def read_symbol(self, node: str, symbol: str) -> float | None:
        """
        Call ReadSymbolVariant(sNodeName, sSymbolName, EasyObject& poData).

        In pythonnet 3.x, 'ref' parameters are passed as-is and the updated
        value is returned as part of the result tuple when the method has
        out/ref params.  We try both conventions.
        """
        log("READ", f"ReadSymbolVariant({node!r}, {symbol!r}) ...")

        # Create an EasyObject to pass as the ref parameter
        easy_obj = None
        if self._eo_type is not None:
            try:
                easy_obj = self._System.Activator.CreateInstance(self._eo_type)
            except Exception as e:
                log("READ", f"  Could not create EasyObject: {e}")

        try:
            if easy_obj is not None:
                # Convention A: ref param — pass instance, result may be (ret, updated_obj)
                result = self._pe.ReadSymbolVariant(node, symbol, easy_obj)
            else:
                # Convention B: treat as out param — pass nothing, get tuple back
                result = self._pe.ReadSymbolVariant(node, symbol)

            log("READ", f"  raw result type : {type(result).__name__}")
            log("READ", f"  raw result value: {result!r}")

            # Unpack return code and EasyObject
            if isinstance(result, (tuple, list)):
                ret_code   = int(result[0]) if len(result) > 0 else -1
                ret_obj    = result[1]       if len(result) > 1 else easy_obj
            else:
                ret_code   = int(result) if result is not None else -1
                ret_obj    = easy_obj

            log("READ", f"  return code: {ret_code}")

            if ret_code != 0:
                msg = self._error_message(ret_code)
                log("READ", f"  ERROR code={ret_code} {msg}")
                return None

            # Extract numeric value from EasyObject
            return self._extract_value(ret_obj, node, symbol)

        except Exception as e:
            log("READ", f"  ReadSymbolVariant exception: {e}")
            traceback.print_exc()
            return None

    # ── ReadDeviceFloat ────────────────────────────────────────────────────────

    def read_device_float(self, node: str, device: str, address: str) -> float | None:
        """
        Try ReadDeviceFloat with multiple parameter conventions and print
        every return code and error message.  Used for diagnostic --test only.
        """
        log("READ_DF", f"ReadDeviceFloat  node={node!r}  device={device!r}  address={address!r}")

        # Create an EasyObject for the ref/out parameter
        easy_obj = None
        if self._eo_type is not None:
            try:
                easy_obj = self._System.Activator.CreateInstance(self._eo_type)
            except Exception as e:
                log("READ_DF", f"  EasyObject creation failed: {e}")

        fn = getattr(self._pe, "ReadDeviceFloat", None)
        if fn is None:
            log("READ_DF", "  ReadDeviceFloat not found on this instance")
            return None

        # Try every likely parameter combination and print the result of each.
        attempts = [
            ("(node, device, address, obj)", lambda: fn(node, device, address, easy_obj)),
            ("(node, device, address)",      lambda: fn(node, device, address)),
            ("(node, address, obj)",          lambda: fn(node, address, easy_obj)),
            ("(node, address)",               lambda: fn(node, address)),
        ]

        for label, call in attempts:
            try:
                result = call()
                log("READ_DF", f"  {label}")
                log("READ_DF", f"    raw result type : {type(result).__name__}")
                log("READ_DF", f"    raw result value: {result!r}")

                # Unpack
                if isinstance(result, (tuple, list)):
                    ret_code = int(result[0]) if len(result) > 0 else -1
                    ret_obj  = result[1]      if len(result) > 1 else easy_obj
                else:
                    ret_code = int(result) if result is not None else -1
                    ret_obj  = easy_obj

                log("READ_DF", f"    return code: {ret_code}")

                if ret_code != 0:
                    msg = self._error_message(ret_code)
                    log("READ_DF", f"    ERROR: code={ret_code} {msg}")
                    # Continue to next attempt
                    continue

                # Success — extract value
                v = self._extract_value(ret_obj, node, address)
                log("READ_DF", f"    VALUE: {v}")
                return v

            except TypeError as e:
                log("READ_DF", f"  {label} → TypeError (wrong signature): {e}")
            except Exception as e:
                log("READ_DF", f"  {label} → Exception: {e}")

        log("READ_DF", f"  All ReadDeviceFloat attempts failed for {address}")
        return None

    def _extract_value(self, obj, node: str, symbol: str) -> float | None:
        """Extract a Python float from an EasyObject.

        ReadSymbolVariant returns GetObject()/GetArray() as System.Single[]
        (a .NET array, No. of Data = 1).  Index [0] to get the scalar.
        """
        if obj is None:
            log("READ", "  EasyObject is None")
            return None

        # GetObject and GetArray both return System.Single[] for scalar symbols.
        # GetStringData is a fallback for string-typed tags.
        for method_name in ("GetObject", "GetArray", "GetStringData"):
            fn = getattr(obj, method_name, None)
            if fn is None:
                continue
            try:
                v = fn()
                log("READ", f"  {method_name}() → type={type(v).__name__}  value={v!r}")
                if v is None:
                    continue

                # ── .NET array (System.Single[], System.Double[], …) ──────────
                # pythonnet exposes .Length on .NET arrays; direct [] indexing works.
                arr_len = getattr(v, "Length", None)
                if arr_len is not None:
                    log("READ", f"    .NET array  length={arr_len}")
                    if arr_len == 0:
                        log("READ", "    array is empty — skipping")
                        continue
                    # Try direct index first (pythonnet 3.x supports this)
                    try:
                        elem = v[0]
                        log("READ", f"    [0] = {elem!r}  (type: {type(elem).__name__})")
                        f = float(elem)
                        log("READ", f"    final float = {f}")
                        return f
                    except (TypeError, IndexError):
                        pass
                    # Fallback: iterate via Python (works on any .NET IEnumerable)
                    for elem in v:
                        log("READ", f"    first element (iter) = {elem!r}  (type: {type(elem).__name__})")
                        f = float(elem)
                        log("READ", f"    final float = {f}")
                        return f
                    continue

                # ── Plain scalar (int, float, str) ────────────────────────────
                f = float(v)
                log("READ", f"    final float = {f}")
                return f

            except (TypeError, ValueError) as e:
                log("READ", f"  {method_name}() conversion failed: {e}")
            except Exception as e:
                log("READ", f"  {method_name}() exception: {e}")

        log("READ", f"  Could not extract float from EasyObject for {symbol}")
        return None


# ── DLL introspection (--inspect) ──────────────────────────────────────────────

def inspect_dll(dll_path: str) -> None:
    """Print all public types and methods from the assembly."""
    import clr                               # noqa: F401
    from System.Reflection import Assembly   # type: ignore

    dll = Path(dll_path)
    log("INSPECT", f"Path   : {dll}")
    log("INSPECT", f"Exists : {dll.exists()}")
    if not dll.exists():
        raise FileNotFoundError(f"Not found: {dll}")

    asm = Assembly.LoadFrom(str(dll))
    log("INSPECT", f"Assembly: {asm.GetName().Name}  v{asm.GetName().Version}")
    print()

    for t in asm.GetExportedTypes():
        print(f"  TYPE: {t.FullName}")
        try:
            for m in sorted(t.GetMethods(), key=lambda x: x.Name):
                try:
                    params = ", ".join(
                        f"{p.ParameterType.Name} {p.Name}"
                        for p in m.GetParameters()
                    )
                    print(f"    {m.ReturnType.Name} {m.Name}({params})")
                except Exception:
                    print(f"    {m.Name}(...)")
        except Exception as e:
            print(f"    (reflection error: {e})")
        print()


# ── HTTP post ──────────────────────────────────────────────────────────────────

def post_reading(backend_url: str, api_key: str,
                 temperature: float | None,
                 pressure:    float | None,
                 ph:          float | None,
                 seq:         int = 0) -> None:
    payload = {
        "api_key":     api_key,
        "timestamp":   datetime.now().isoformat(),
        "source":      "proserver",
        "temperature": temperature,
        "pressure":    pressure,
        "ph":          ph,
    }
    resp = requests.post(backend_url, json=payload, timeout=5)
    # Diagnostic block — full precision, ms timestamp, sequence number
    ts_ms = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[COLLECTOR] {ts_ms} #{seq}", flush=True)
    print(f"T={temperature}", flush=True)
    print(f"P={pressure}", flush=True)
    print(f"pH={ph}", flush=True)
    print(f"POST={resp.status_code}", flush=True)
    print(flush=True)
    resp.raise_for_status()


# ── --test mode ────────────────────────────────────────────────────────────────

def run_test(config: dict) -> None:
    print()
    print("=" * 60)
    print("  PROSERVER COLLECTOR — ONE-SHOT TEST")
    print("=" * 60)
    print()

    dll_path    = config["dll_path"]
    node        = config["node"]
    symbols     = config["readings"]   # {field: {symbol, address, type}}

    session = ProEasySession(dll_path)
    print()
    session.init()
    print()

    device      = config.get("device", "PLC1")

    # ── Phase 1: ReadSymbolVariant ──────────────────────────────────────────
    print("-" * 60)
    print("  PHASE 1: ReadSymbolVariant")
    print("-" * 60)
    values: dict[str, float | None] = {}
    try:
        for field, cfg in symbols.items():
            symbol_name = cfg.get("symbol", field)
            log("READ", f"--- {field} ({symbol_name}) ---")
            v = session.read_symbol(node, symbol_name)
            values[field] = v
            print()
    except Exception as e:
        log("READ", f"Unhandled exception in ReadSymbolVariant loop: {e}")
    finally:
        pass  # keep session alive for Phase 2

    print("-" * 40)
    print("  ReadSymbolVariant summary")
    print("-" * 40)
    for field, v in values.items():
        print(f"  {field:<15} {v if v is not None else 'FAILED'}")
    print()

    # ── Phase 2: ReadDeviceFloat ────────────────────────────────────────────
    print("-" * 60)
    print("  PHASE 2: ReadDeviceFloat (direct D-register read)")
    print("-" * 60)
    df_values: dict[str, float | None] = {}
    try:
        for field, cfg in symbols.items():
            address = cfg.get("address", "")
            log("READ_DF", f"=== {field}  address={address} ===")
            v = session.read_device_float(node, device, address)
            df_values[field] = v
            print()
    except Exception as e:
        log("READ_DF", f"Unhandled exception in ReadDeviceFloat loop: {e}")
    finally:
        session.term()

    print("-" * 40)
    print("  ReadDeviceFloat summary")
    print("-" * 40)
    for field, v in df_values.items():
        print(f"  {field:<15} {v if v is not None else 'FAILED'}")
    print()

    any_symbol_ok = any(v is not None for v in values.values())

    print("-" * 60)
    print("  FINAL SUMMARY")
    print("-" * 60)
    status_label = {True: "SUCCESS", False: "FAILED"}
    for field in symbols:
        sv = values.get(field)
        print(f"  {field:<15} {status_label[sv is not None]:<10} {sv if sv is not None else ''}")
    print()

    if not any_symbol_ok:
        print("All reads failed — backend POST suppressed.")
        sys.exit(1)

    # ── POST to backend ─────────────────────────────────────────────────────
    backend_url = config["backend_url"]
    api_key     = config["api_key"]
    try:
        post_reading(backend_url, api_key,
                     values.get("temperature"),
                     values.get("pressure"),
                     values.get("ph"))
        log("HTTP", "POST succeeded")
    except Exception as e:
        log("HTTP", f"POST failed: {e}")
        sys.exit(1)

    # Verify backend received it
    status_url = backend_url.rsplit("/", 1)[0] + "/status"
    try:
        r = requests.get(status_url, timeout=5)
        d = r.json()
        print()
        print("-" * 40)
        print("  BACKEND /collector/status")
        print("-" * 40)
        print(f"  connection_state : {d.get('connection_state')}")
        print(f"  total_received   : {d.get('total_received')}")
        lr = d.get("latest_reading") or {}
        print(f"  temperature      : {lr.get('temperature')}")
        print(f"  pressure         : {lr.get('pressure')}")
        print(f"  ph               : {lr.get('ph')}")
    except Exception as e:
        log("HTTP", f"GET /status failed: {e}")

    print()
    print("=" * 60)
    print("  TEST COMPLETE")
    print("=" * 60)


# ── continuous mode ────────────────────────────────────────────────────────────

def run_continuous(config: dict) -> None:
    dll_path      = config["dll_path"]
    node          = config["node"]
    backend_url   = config["backend_url"]
    api_key       = config["api_key"]
    symbols       = config["readings"]
    poll_interval = float(config.get("poll_interval_seconds", 5))

    # Same symbol-name derivation the read loop below uses, computed once so
    # the cache is registered with exactly the names read_symbol() will query.
    symbol_names = [cfg.get("symbol", field) for field, cfg in symbols.items()]

    log("COLLECTOR", f"Backend  : {backend_url}")
    log("COLLECTOR", f"Node     : {node}")
    log("COLLECTOR", f"Interval : {poll_interval}s")
    print()

    session = None
    cycle   = 0

    while True:
        cycle_start = time.monotonic()
        try:
            if session is None:
                session = ProEasySession(dll_path)
                session.init()
                session.start_cache(node, symbol_names)
                log("COLLECTOR", "Connected to Pro-Server EX")
                log("COLLECTOR", "SentinelEdge runtime cache active")
                print()

            cycle += 1
            values: dict[str, float | None] = {}
            for field, cfg in symbols.items():
                symbol_name = cfg.get("symbol", field)
                values[field] = session.read_symbol(node, symbol_name)

            if any(v is not None for v in values.values()):
                post_reading(backend_url, api_key,
                             values.get("temperature"),
                             values.get("pressure"),
                             values.get("ph"),
                             seq=cycle)
            else:
                log("COLLECTOR", f"#{cycle} all reads null — skipping POST")

        except KeyboardInterrupt:
            log("COLLECTOR", "Ctrl+C — stopping")
            if session:
                session.stop_cache()
                session.term()
            sys.exit(0)

        except Exception:
            log("COLLECTOR", "Exception — reconnecting on next cycle")
            traceback.print_exc()
            if session:
                try:
                    session.stop_cache()
                except Exception:
                    pass
                try:
                    session.term()
                except Exception:
                    pass
            session = None

        # Sleep only the remainder so the START of each cycle is poll_interval
        # apart (read + POST already consumes ~3.5 s of it).
        elapsed   = time.monotonic() - cycle_start
        remaining = max(0.0, poll_interval - elapsed)
        time.sleep(remaining)


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_config()

    if "--inspect" in sys.argv:
        inspect_dll(cfg["dll_path"])
    elif "--test" in sys.argv:
        run_test(cfg)
    else:
        run_continuous(cfg)
