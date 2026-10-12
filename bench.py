#!/usr/bin/env python3
"""
machine-bench: System performance benchmarking tool.
Tests CPU (single + multi-core), memory bandwidth, and disk I/O.
"""

import time
import math
import os
import sys
import platform
import multiprocessing
import tempfile
import array
import json
import datetime
from contextlib import contextmanager

# ── History ───────────────────────────────────────────────────────────────────

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_run(scores: dict, overall: float, rating: str):
    history = load_history()
    entry = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "version":   VERSION,
        "os":        f"{platform.system()} {platform.release()}",
        "machine":   platform.machine(),
        "cpu_cores": multiprocessing.cpu_count(),
        "scores":    {k: round(v, 2) for k, v in scores.items()},
        "overall":   round(overall, 2),
        "rating":    rating,
    }
    history.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    return entry


def print_history():
    history = load_history()
    if not history:
        return
    separator("RUN HISTORY")
    headers = ["#", "Timestamp", "Overall", "Rating", "CPU-S", "CPU-M", "Mem", "Disk"]
    col_w   = [3, 19, 9, 13, 7, 7, 7, 7]
    header  = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w))
    print(header)
    print("  " + "  ".join("─" * w for w in col_w))
    for i, r in enumerate(history, 1):
        s = r.get("scores", {})
        cols = [
            str(i),
            r["timestamp"],
            f"{r['overall']:.1f}",
            r["rating"],
            f"{s.get('CPU Single-Core', 0):.1f}",
            f"{s.get('CPU Multi-Core', 0):.1f}",
            f"{s.get('Memory', 0):.1f}",
            f"{s.get('Disk', 0):.1f}",
        ]
        print("  " + "  ".join(c.ljust(w) for c, w in zip(cols, col_w)))

# ── Version ───────────────────────────────────────────────────────────────────

VERSION = "0.1.0"

# ── Benchmark Parameters ──────────────────────────────────────────────────────

CPU_ITERATIONS       = 5_000_000
MULTICORE_ITERATIONS = 2_000_000
MEMORY_SIZE_MB       = 512      # bytearray bulk copy test
DISK_FILE_SIZE_MB    = 512

# ── Score Baselines (100 pts == decent mid-range machine) ─────────────────────

BASELINE_CPU_SINGLE  = 8.0      # MOps/s
BASELINE_CPU_MULTI   = 40.0     # MOps/s total
BASELINE_MEMORY_BW   = 15_000   # MB/s (bulk bytearray copy)
BASELINE_DISK_WRITE  = 1_500    # MB/s
BASELINE_DISK_READ   = 3_000    # MB/s

# ── Helpers ───────────────────────────────────────────────────────────────────

@contextmanager
def timer():
    start = time.perf_counter()
    result = {}
    yield result
    result["elapsed"] = time.perf_counter() - start


def separator(title=""):
    width = 60
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * (width - pad - len(title) - 2)}")
    else:
        print("─" * width)


def row(label, value, unit, score=None):
    base = f"  {label:<32} {value:>10.2f} {unit}"
    if score is not None:
        base += f"   [{score:>5.1f} pts]"
    print(base)


def normalize(value, baseline):
    """Scale value so that baseline == 100 pts."""
    return (value / baseline) * 100


# ── System Info ───────────────────────────────────────────────────────────────

def print_system_info():
    separator("SYSTEM INFO")
    cpu_count = multiprocessing.cpu_count()
    print(f"  OS              : {platform.system()} {platform.release()}")
    print(f"  Machine         : {platform.machine()}")
    print(f"  Processor       : {platform.processor() or 'N/A'}")
    print(f"  CPU cores       : {cpu_count} logical")
    print(f"  Python          : {sys.version.split()[0]}")


# ── CPU Single-Core ───────────────────────────────────────────────────────────

def _cpu_workload(n):
    total = 0.0
    for i in range(1, n + 1):
        total += math.sqrt(i) * math.log(i) / (math.sin(i % 100 + 0.001) + 2)
    return total


def bench_cpu_single():
    separator("CPU — SINGLE CORE")
    runs = 3
    times = []
    for i in range(runs):
        with timer() as t:
            _cpu_workload(CPU_ITERATIONS)
        times.append(t["elapsed"])
        print(f"  Run {i + 1}: {t['elapsed']:.3f}s")

    best = min(times)
    mops = CPU_ITERATIONS / best / 1_000_000
    score = normalize(mops, BASELINE_CPU_SINGLE)

    print()
    row("Best time", best, "s")
    row("Throughput", mops, "MOps/s", score)
    return score


# ── CPU Multi-Core ────────────────────────────────────────────────────────────

def _worker(_):
    return _cpu_workload(MULTICORE_ITERATIONS)


def bench_cpu_multi():
    separator("CPU — MULTI CORE")
    cpu_count = multiprocessing.cpu_count()
    print(f"  Spawning {cpu_count} workers...")

    with timer() as t:
        with multiprocessing.Pool(processes=cpu_count) as pool:
            pool.map(_worker, range(cpu_count))

    total_ops = MULTICORE_ITERATIONS * cpu_count
    mops = total_ops / t["elapsed"] / 1_000_000
    score = normalize(mops, BASELINE_CPU_MULTI)

    print()
    row("Elapsed", t["elapsed"], "s")
    row("Total throughput", mops, "MOps/s", score)
    return score


# ── Memory Bandwidth ──────────────────────────────────────────────────────────

def bench_memory():
    """
    Uses bulk bytearray slice assignment and memoryview copies to measure
    memory copy throughput at near-C speed, bypassing Python iteration overhead.
    """
    separator("MEMORY BANDWIDTH")
    total_bytes = MEMORY_SIZE_MB * 1024 * 1024
    chunk_size  = 1024 * 1024  # 1 MB
    chunk       = bytes(chunk_size)  # zero-filled source block (C-allocated)

    print(f"  Buffer size : {MEMORY_SIZE_MB} MB")
    print(f"  Chunk size  : {chunk_size // (1024*1024)} MB")

    buf = bytearray(total_bytes)

    # Write: bulk slice assignment (C memcpy internally)
    with timer() as t_write:
        for i in range(0, total_bytes, chunk_size):
            buf[i:i + chunk_size] = chunk
    write_bw = MEMORY_SIZE_MB / t_write["elapsed"]

    # Read: bulk bytes conversion via memoryview (C-level copy)
    mv = memoryview(buf)
    with timer() as t_read:
        for i in range(0, total_bytes, chunk_size):
            _ = bytes(mv[i:i + chunk_size])
    read_bw = MEMORY_SIZE_MB / t_read["elapsed"]

    del buf, mv

    avg_bw = (write_bw + read_bw) / 2
    score  = normalize(avg_bw, BASELINE_MEMORY_BW)

    print()
    row("Write bandwidth", write_bw, "MB/s")
    row("Read bandwidth",  read_bw,  "MB/s")
    row("Avg bandwidth",   avg_bw,   "MB/s", score)
    return score


# ── Disk I/O ──────────────────────────────────────────────────────────────────

def _try_bypass_cache(fd):
    """Attempt to disable OS read cache (macOS + Linux)."""
    try:
        import fcntl
        if hasattr(fcntl, "F_NOCACHE"):       # macOS
            fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
        elif hasattr(os, "O_DIRECT"):          # Linux (not always available via Python)
            pass
    except Exception:
        pass


def bench_disk():
    separator("DISK I/O")
    size_bytes = DISK_FILE_SIZE_MB * 1024 * 1024
    chunk_size = 1024 * 1024  # 1 MB
    chunk = os.urandom(chunk_size)
    chunks = DISK_FILE_SIZE_MB

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bench")
    path = tmp.name
    tmp.close()

    note = ""

    try:
        # Sequential write (with fsync to flush to storage controller)
        with timer() as t_write:
            with open(path, "wb") as f:
                _try_bypass_cache(f.fileno())
                for _ in range(chunks):
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())
        write_mb_s = DISK_FILE_SIZE_MB / t_write["elapsed"]

        # Drop the file from Python's buffer, re-open to read
        with timer() as t_read:
            with open(path, "rb") as f:
                _try_bypass_cache(f.fileno())
                while f.read(chunk_size):
                    pass
        read_mb_s = DISK_FILE_SIZE_MB / t_read["elapsed"]

    finally:
        os.unlink(path)

    # Warn if numbers suggest page cache is dominating
    cache_threshold = 8_000  # MB/s — above this almost certainly cached
    if write_mb_s > cache_threshold or read_mb_s > cache_threshold:
        note = "  * Results may include OS page cache. Run 'sudo purge' first for raw SSD speed."

    avg_mb_s = (write_mb_s + read_mb_s) / 2
    score_w = normalize(write_mb_s, BASELINE_DISK_WRITE)
    score_r = normalize(read_mb_s, BASELINE_DISK_READ)
    score = (score_w + score_r) / 2

    print()
    row("Sequential write", write_mb_s, "MB/s", score_w)
    row("Sequential read", read_mb_s, "MB/s", score_r)
    row("Avg score", avg_mb_s, "MB/s", score)
    if note:
        print(f"\n{note}")
    return score


# ── Summary ───────────────────────────────────────────────────────────────────

WEIGHTS = {
    "CPU Single-Core": 0.25,
    "CPU Multi-Core":  0.35,
    "Memory":          0.25,
    "Disk":            0.15,
}

RATINGS = [
    (150, "Excellent"),
    (100, "Good"),
    (60,  "Average"),
    (0,   "Below Average"),
]


def print_summary(scores: dict):
    separator("SUMMARY")
    weighted_total = sum(scores[k] * WEIGHTS[k] for k in scores if k in WEIGHTS)

    for label, pts in scores.items():
        row(label, pts, "pts", pts)
    print()
    print(f"  {'Weighted Overall Score':<32} {weighted_total:>10.1f} pts")
    separator()

    rating = next(r for threshold, r in RATINGS if weighted_total >= threshold)
    print(f"  Rating: {rating}  (baseline machine = 100 pts)\n")
    return weighted_total, rating


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    print(f"\n  machine-bench v{VERSION}")
    separator()
    print_system_info()

    scores = {}

    for name, fn in [
        ("CPU Single-Core", bench_cpu_single),
        ("CPU Multi-Core",  bench_cpu_multi),
        ("Memory",          bench_memory),
        ("Disk",            bench_disk),
    ]:
        try:
            scores[name] = fn()
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    if scores:
        overall, rating = print_summary(scores)
        save_run(scores, overall, rating)
        print(f"  Run saved to: {HISTORY_FILE}")
        print()
        print_history()


if __name__ == "__main__":
    main()
