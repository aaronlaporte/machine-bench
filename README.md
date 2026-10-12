# machine-bench

A lightweight, dependency-free system benchmarking tool. Tests CPU, memory, and disk performance and outputs a weighted overall score.

## Benchmarks

| Test | What it measures |
|---|---|
| CPU Single-Core | Floating-point math throughput on one core |
| CPU Multi-Core | Parallel math throughput across all logical cores |
| Memory Bandwidth | Raw read/write speed against a large in-memory buffer |
| Disk I/O | Sequential read/write speed with fsync |

## Usage

```bash
python bench.py
```

No dependencies. Requires Python 3.8+.

## Output

```
  machine-bench v0.1.0
────────────────────────────────────────────────────────────
──────────────────── SYSTEM INFO ───────────────────────────
  OS              : Darwin 24.x.x
  CPU cores       : 10 logical
  ...

──────────────────── SUMMARY ───────────────────────────────
  CPU Single-Core                     85.3 pts
  CPU Multi-Core                     210.7 pts
  Memory                              42.1 pts
  Disk                                38.9 pts

  Overall Score                      121.4 pts
  Rating: Good
```

## Scoring

Scores are weighted:

- CPU Single-Core: 30%
- CPU Multi-Core: 35%
- Memory: 20%
- Disk: 15%

| Rating | Score |
|---|---|
| Excellent | 150+ |
| Good | 80–149 |
| Average | 40–79 |
| Below Average | <40 |
