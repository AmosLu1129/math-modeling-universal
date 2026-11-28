#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opt-in modular solver stage cache keyed by parameters, input files, and code hashes.

Designed for multi-stage modeling pipelines (upstream simulation / optimization ->
downstream sensitivity, bootstrap, and counterfactual analysis) so downstream
tweaks do not force multi-minute upstream recomputations while preserving
deterministic invalidation whenever inputs, code, or parameters change.

Cache artifacts live under `work/scratch/cache/` by default (auto-excluded from
final deliverables by `pack_submission.py`). Set `MM_FORCE_RECOMPUTE=1` for final
clean-slate production verification.

Usage (Python API):
    from stage_cache import StageCache
    cache = StageCache("work/scratch/cache")
    particles = cache.run_stage(
        "q1_simulation",
        lambda: run_sim(seed=42),
        params={"n_particles": 4000, "seed": 42},
        inputs=["work/data_clean/obs.csv"],
        code_files=[__file__],
        fmt="npz",
    )

Usage (CLI):
    python stage_cache.py --inspect work/scratch/cache
    python stage_cache.py --clear work/scratch/cache [--stage q1_simulation]
    python stage_cache.py --self-test
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import re
import sys
import tempfile
import time
from typing import Any, Callable, Sequence, TypeVar

T = TypeVar("T")

_EXT_MAP = {
    "json": ".json",
    "npz": ".npz",
    "pickle": ".pkl",
}


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_stage_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return cleaned or "stage"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted((_json_default(x) for x in obj), key=str)
    if isinstance(obj, bytes):
        return obj.hex()
    # Handle numpy scalars/arrays cleanly if numpy happens to be present
    item = getattr(obj, "item", None)
    if callable(item) and type(obj).__module__.startswith("numpy"):
        return item()
    tolist = getattr(obj, "tolist", None)
    if callable(tolist) and type(obj).__module__.startswith("numpy"):
        return tolist()
    return str(obj)


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"StageCache dependency file not found: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{target.name}.{os.getpid()}.tmp"
    try:
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _human_size(num_bytes: int) -> str:
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024.0 or unit == "GB":
            return f"{int(val)} B" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{num_bytes} B"


class StageCache:
    """Content-addressed cache for modular solver stages."""

    def __init__(self, cache_dir: str | Path = "work/scratch/cache", enabled: bool = True) -> None:
        self.cache_dir = Path(cache_dir)
        self.enabled = bool(enabled)

    def fingerprint(
        self,
        params: dict[str, Any] | None = None,
        inputs: Sequence[str | Path] = (),
        code_files: Sequence[str | Path] = (),
    ) -> str:
        """Compute deterministic 16-hex SHA-256 fingerprint over params, inputs, and code."""
        input_hashes = []
        for p in sorted((Path(x) for x in inputs), key=lambda item: str(item)):
            input_hashes.append({"path": str(p), "sha256": _sha256_file(p)})

        code_hashes = []
        for p in sorted((Path(x) for x in code_files), key=lambda item: str(item)):
            code_hashes.append({"path": str(p), "sha256": _sha256_file(p)})

        payload = {
            "params": params if params is not None else {},
            "inputs": input_hashes,
            "code_files": code_hashes,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_json_default)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def _is_forced(self, name: str, safe_name: str, force: bool) -> bool:
        if force or _env_truthy("MM_FORCE_RECOMPUTE"):
            return True
        raw_list = os.environ.get("MM_FORCE_STAGES", "").strip()
        if not raw_list:
            return False
        targets = {tok.strip() for tok in raw_list.split(",") if tok.strip()}
        return name in targets or safe_name in targets

    def _load_payload(self, data_path: Path, fmt: str, meta: dict[str, Any]) -> Any:
        if fmt == "json":
            return json.loads(data_path.read_text(encoding="utf-8"))
        if fmt == "pickle":
            with data_path.open("rb") as f:
                return pickle.load(f)
        if fmt == "npz":
            import numpy as np

            with np.load(data_path, allow_pickle=False) as arc:
                if meta.get("npz_wrapped_single") and "_array" in arc.files and len(arc.files) == 1:
                    return np.array(arc["_array"])
                return {k: np.array(arc[k]) for k in arc.files}
        raise ValueError(f"Unsupported cache format: {fmt!r}")

    def _save_payload(self, data_path: Path, fmt: str, value: Any) -> dict[str, Any]:
        extra_meta: dict[str, Any] = {}
        data_path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            encoded = json.dumps(value, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
            _atomic_write_bytes(data_path, encoded)
            return extra_meta

        if fmt == "pickle":
            _atomic_write_bytes(data_path, pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
            return extra_meta

        if fmt == "npz":
            import numpy as np

            tmp = data_path.parent / f".{data_path.name}.{os.getpid()}.tmp"
            try:
                with tmp.open("wb") as f:
                    if isinstance(value, dict):
                        np.savez_compressed(f, **value)
                    else:
                        extra_meta["npz_wrapped_single"] = True
                        np.savez_compressed(f, _array=value)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, data_path)
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
            return extra_meta

        raise ValueError(f"Unsupported cache format: {fmt!r} (choose 'json', 'npz', or 'pickle')")

    def run_stage(
        self,
        name: str,
        fn: Callable[[], T],
        *,
        params: dict[str, Any] | None = None,
        inputs: Sequence[str | Path] = (),
        code_files: Sequence[str | Path] = (),
        force: bool = False,
        fmt: str = "json",
        quiet: bool = False,
    ) -> T:
        """Execute `fn()` or return cached result if fingerprint matches."""
        if fmt not in _EXT_MAP:
            raise ValueError(f"Unsupported cache format: {fmt!r} (choose 'json', 'npz', or 'pickle')")

        safe_name = _sanitize_stage_name(name)
        fp = self.fingerprint(params=params, inputs=inputs, code_files=code_files)

        cache_active = self.enabled and not _env_truthy("MM_DISABLE_CACHE")
        forced = self._is_forced(name, safe_name, force)

        meta_path = self.cache_dir / f"{safe_name}.meta.json"
        data_path = self.cache_dir / f"{safe_name}{_EXT_MAP[fmt]}"

        if cache_active and not forced and meta_path.is_file() and data_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("fingerprint") == fp and meta.get("format") == fmt:
                    cached = self._load_payload(data_path, fmt, meta)
                    if not quiet:
                        print(f"[StageCache] HIT  {name} (fp={fp})")
                    return cached
            except Exception:
                pass

        t0 = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - t0

        if cache_active:
            extra_meta = self._save_payload(data_path, fmt, result)
            meta = {
                "stage": name,
                "safe_name": safe_name,
                "format": fmt,
                "fingerprint": fp,
                "elapsed_sec": round(elapsed, 4),
                "size_bytes": data_path.stat().st_size if data_path.is_file() else 0,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "data_file": data_path.name,
                **extra_meta,
            }
            _atomic_write_bytes(
                meta_path,
                json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"),
            )

        if not quiet:
            print(f"[StageCache] MISS {name} -> computed in {elapsed:.2f}s (fp={fp})")
        return result

    def inspect(self) -> list[dict[str, Any]]:
        """Return metadata records for all cached stages sorted by stage name."""
        if not self.cache_dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for meta_path in sorted(self.cache_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                data_name = meta.get("data_file")
                data_exists = bool(data_name and (self.cache_dir / data_name).is_file())
                if "size_bytes" not in meta and data_exists:
                    meta["size_bytes"] = (self.cache_dir / data_name).stat().st_size
                meta["valid_payload"] = data_exists
                records.append(meta)
            except Exception:
                continue
        return records

    def clear(self, stage: str | None = None) -> int:
        """Clear cached entries (all stages or a single named stage). Returns stages removed."""
        if not self.cache_dir.is_dir():
            return 0
        target_safe = _sanitize_stage_name(stage) if stage else None
        removed_stages = 0

        if target_safe is not None:
            matched_any = False
            for ext in (".meta.json", *_EXT_MAP.values()):
                p = self.cache_dir / f"{target_safe}{ext}"
                if p.is_file():
                    p.unlink()
                    matched_any = True
            return 1 if matched_any else 0

        seen_stems: set[str] = set()
        for meta_path in list(self.cache_dir.glob("*.meta.json")):
            stem = meta_path.name[: -len(".meta.json")]
            seen_stems.add(stem)
            meta_path.unlink()
        for ext in _EXT_MAP.values():
            for data_path in list(self.cache_dir.glob(f"*{ext}")):
                seen_stems.add(data_path.stem)
                data_path.unlink()
        removed_stages = len(seen_stems)
        return removed_stages


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="stage_cache_test_") as td:
        tdir = Path(td)
        cache_dir = tdir / "cache"
        inp = tdir / "input.csv"
        code_f = tdir / "solver.py"
        inp.write_text("x,y\n1,2\n", encoding="utf-8")
        code_f.write_text("VERSION = 1\n", encoding="utf-8")

        cache = StageCache(cache_dir)
        calls = 0

        def _compute_json(mult: int) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return {"calls": calls, "val": mult * 10}

        # 1. Miss -> Hit
        r1 = cache.run_stage("q1_stage", lambda: _compute_json(2), params={"k": 1}, inputs=[inp], code_files=[code_f], quiet=True)
        r2 = cache.run_stage("q1_stage", lambda: _compute_json(2), params={"k": 1}, inputs=[inp], code_files=[code_f], quiet=True)
        assert calls == 1 and r1 == r2 == {"calls": 1, "val": 20}, (calls, r1, r2)

        # 2. Param change -> Miss
        r3 = cache.run_stage("q1_stage", lambda: _compute_json(3), params={"k": 2}, inputs=[inp], code_files=[code_f], quiet=True)
        assert calls == 2 and r3["val"] == 30, (calls, r3)

        # 3. Input file content change -> Miss
        inp.write_text("x,y\n1,99\n", encoding="utf-8")
        r4 = cache.run_stage("q1_stage", lambda: _compute_json(3), params={"k": 2}, inputs=[inp], code_files=[code_f], quiet=True)
        assert calls == 3 and r4["calls"] == 3, (calls, r4)

        # 4. Explicit force=True & MM_FORCE_STAGES env -> Miss
        r5 = cache.run_stage("q1_stage", lambda: _compute_json(4), params={"k": 2}, inputs=[inp], code_files=[code_f], force=True, quiet=True)
        assert calls == 4 and r5["val"] == 40, (calls, r5)

        prev_env = os.environ.get("MM_FORCE_STAGES")
        try:
            os.environ["MM_FORCE_STAGES"] = "other_stage,q1_stage"
            r6 = cache.run_stage("q1_stage", lambda: _compute_json(5), params={"k": 2}, inputs=[inp], code_files=[code_f], quiet=True)
            assert calls == 5 and r6["val"] == 50, (calls, r6)
        finally:
            if prev_env is None:
                os.environ.pop("MM_FORCE_STAGES", None)
            else:
                os.environ["MM_FORCE_STAGES"] = prev_env

        # 5. Pickle & optional NPZ roundtrip
        pkl_calls = 0

        def _compute_pkl() -> tuple[int, str]:
            nonlocal pkl_calls
            pkl_calls += 1
            return (42, "ok")

        p1 = cache.run_stage("pkl_stage", _compute_pkl, fmt="pickle", quiet=True)
        p2 = cache.run_stage("pkl_stage", _compute_pkl, fmt="pickle", quiet=True)
        assert pkl_calls == 1 and p1 == p2 == (42, "ok")

        npz_label = ""
        try:
            import numpy as np

            npz_calls = 0

            def _compute_npz() -> dict[str, Any]:
                nonlocal npz_calls
                npz_calls += 1
                return {"pts": np.array([[1.0, 2.0], [3.0, 4.0]])}

            n1 = cache.run_stage("npz_stage", _compute_npz, fmt="npz", quiet=True)
            n2 = cache.run_stage("npz_stage", _compute_npz, fmt="npz", quiet=True)
            assert npz_calls == 1 and np.allclose(n1["pts"], n2["pts"])
            npz_label = "+npz"
        except ImportError:
            npz_label = ""

        # 6. Inspect & clear
        entries = cache.inspect()
        expected_cnt = 3 if npz_label else 2
        assert len(entries) == expected_cnt, entries
        assert cache.clear("q1_stage") == 1
        assert len(cache.inspect()) == expected_cnt - 1
        assert cache.clear() == expected_cnt - 1
        assert cache.inspect() == []

    print(f"[SELF-TEST] PASS stage_cache (fingerprint invalidation, force/env override, json+pickle{npz_label}, inspect/clear)")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    ap = argparse.ArgumentParser(description="Modular solver stage cache inspector & cleaner")
    ap.add_argument("--inspect", default="", help="查看指定缓存目录内的所有阶段记录")
    ap.add_argument("--clear", default="", help="清理指定缓存目录的阶段缓存")
    ap.add_argument("--stage", default="", help="配合 --clear 仅清理指定阶段名")
    ap.add_argument("--self-test", action="store_true", help="运行内置自检")
    args = ap.parse_args()

    if args.inspect:
        cache = StageCache(args.inspect)
        entries = cache.inspect()
        if not entries:
            print(f"[StageCache] No cached stages found in {args.inspect}")
            return 0
        print(f"{'Stage':<24} {'Fmt':<7} {'Fingerprint':<18} {'Time(s)':<9} {'Size':<10} {'Created At'}")
        print("-" * 92)
        for rec in entries:
            print(
                f"{str(rec.get('stage', '')):<24} "
                f"{str(rec.get('format', '')):<7} "
                f"{str(rec.get('fingerprint', '')):<18} "
                f"{str(rec.get('elapsed_sec', '')):<9} "
                f"{_human_size(int(rec.get('size_bytes', 0))):<10} "
                f"{rec.get('created_at', '')}"
            )
        return 0

    if args.clear:
        cache = StageCache(args.clear)
        removed = cache.clear(args.stage or None)
        print(f"[StageCache] Cleared {removed} stage entry/entries in {args.clear}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
