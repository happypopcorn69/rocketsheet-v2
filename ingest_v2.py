#!/usr/bin/env python3
"""
ingest_v2.py
================

This is the current workhorse ingestor for the RocketSheet v2 log‑first
performance pipeline.  It consumes one or more Space Engineers 2 log
files, produces a canonical event stream (``events.jsonl``) and a tidy
``metrics.csv`` table, and supports basic tagging of the resulting
records with metadata provided on the command line.  Unlike the MVP
prototype, this script has built‑in logic for the core log lines and
does not require an external pattern file.  See the README for
examples of how to invoke the ingestor.
"""

import argparse
import csv
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LogMetrics:
    """Container for metrics accumulated while parsing a single log file."""

    # Loading times keyed by scenario label (e.g. Session, ReturnToMenu)
    loading_times: Dict[str, float] = field(default_factory=dict)
    # Aggregated samples keyed by subcomponent (e.g. GPUTime, RenderThread)
    aggregate_samples: Dict[str, List[float]] = field(default_factory=dict)
    # Raw frametime samples (milliseconds) computed from FPS lines
    frametimes: List[float] = field(default_factory=list)

    def record_loading_time(self, label: str, value: float) -> None:
        # Record the last loading time observed for a given label
        self.loading_times[label] = value

    def record_aggregate(self, legend: List[str], values: List[float]) -> None:
        # Extend aggregate sample lists for each component
        for label, val in zip(legend, values):
            self.aggregate_samples.setdefault(label, []).append(val)

    def record_fps(self, fps: float) -> None:
        # Convert FPS to frametime in milliseconds and store
        if fps > 0:
            self.frametimes.append(1000.0 / fps)


def infer_role(filename: str, rolemap: Optional[Dict[str, str]]) -> str:
    """
    Infer the source role (client/server/dedicated/unknown) from the
    filename or from a user‑supplied rolemap.  The rules follow the
    README documentation.
    """
    base = os.path.basename(filename)
    if rolemap and base in rolemap:
        return rolemap[base]
    lower = base.lower()
    if "client" in lower:
        return "client"
    if "server" in lower and "client" not in lower:
        return "server"
    if "dedicated" in lower:
        return "dedicated"
    return "unknown"


def read_rolemap(path: Optional[str]) -> Optional[Dict[str, str]]:
    """Read a filename→role mapping file if provided."""
    if not path:
        return None
    mapping: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                fname, role = line.split("=", 1)
                mapping[fname.strip()] = role.strip()
    except OSError:
        # Silently ignore missing rolemap
        pass
    return mapping or None


def parse_log_file(path: str, metrics: LogMetrics, events_fh) -> None:
    """
    Parse a single log file, emitting JSON events and updating metrics.

    :param path: Path to the log file.
    :param metrics: Accumulator for metrics.
    :param events_fh: Open file handle to which JSON events will be written.
    """
    # Regular expressions for the core log lines
    loading_re = re.compile(r"^LOADING_TIME\|([^=|]+)[=|]([0-9]+(?:\.[0-9]+)?)")
    aggregate_re = re.compile(r"^AGGREGATE_([^|]+)\|([^|]*)\|(.+)")
    fps_re = re.compile(r"Perf: FPS=([0-9]+(?:\.[0-9]+)?)")

    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            raw = line.rstrip("\n")
            event: Dict[str, object] = {"raw": raw}
            # Parse loading times
            m = loading_re.match(raw)
            if m:
                label = m.group(1).strip()
                try:
                    value = float(m.group(2))
                except ValueError:
                    value = 0.0
                metrics.record_loading_time(label, value)
                event["kv"] = {"type": "loading_time", "label": label, "value": value}
                events_fh.write(json.dumps(event) + "\n")
                continue

            # Parse aggregates
            m = aggregate_re.match(raw)
            if m:
                # Name of the aggregate group (not used yet)
                # name = m.group(1)
                legend_str = m.group(2)
                values_str = m.group(3)
                legend = [s.strip() for s in legend_str.split(";") if s.strip()]
                vals: List[float] = []
                for token in values_str.split(";"):
                    token = token.strip()
                    if not token:
                        continue
                    try:
                        vals.append(float(token))
                    except ValueError:
                        vals.append(0.0)
                metrics.record_aggregate(legend, vals)
                event["kv"] = {"type": "aggregate", "legend": legend, "values": vals}
                events_fh.write(json.dumps(event) + "\n")
                continue

            # Parse FPS lines
            m = fps_re.search(raw)
            if m:
                try:
                    fps_val = float(m.group(1))
                    metrics.record_fps(fps_val)
                    event["kv"] = {"type": "fps", "fps": fps_val}
                except ValueError:
                    pass
                events_fh.write(json.dumps(event) + "\n")
                continue

            # Default: no kv
            events_fh.write(json.dumps(event) + "\n")


def compute_metrics(metrics: LogMetrics) -> Dict[str, float]:
    """
    Aggregate raw samples into high‑level metrics.  Returns a mapping
    from metric_id → numeric value.
    """
    result: Dict[str, float] = {}

    # Loading times: use last value per label
    for label, val in metrics.loading_times.items():
        metric_id = f"loading_time_{label}_ms"
        result[metric_id] = val

    # Aggregate samples: compute median per legend entry
    for label, vals in metrics.aggregate_samples.items():
        if not vals:
            continue
        try:
            median_val = statistics.median(vals)
        except statistics.StatisticsError:
            median_val = 0.0
        metric_id = f"aggregate_median_{label}"
        result[metric_id] = median_val

    # Frametime percentiles: compute p50/p95 when samples exist
    if metrics.frametimes:
        sorted_frames = sorted(metrics.frametimes)
        n = len(sorted_frames)
        # Helper to compute percentile (nearest rank method)
        def percentile(data: List[float], pct: float) -> float:
            if not data:
                return 0.0
            k = int(round((len(data) - 1) * pct))
            return data[k]
        result["frametime_p50_ms"] = percentile(sorted_frames, 0.50)
        result["frametime_p95_ms"] = percentile(sorted_frames, 0.95)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Space Engineers logs and emit events and metrics (v2)")
    parser.add_argument("--in", dest="indir", required=True, help="Directory containing input log files")
    parser.add_argument("--out", dest="outdir", required=True, help="Directory to write output files")
    parser.add_argument("--machine", required=True, help="Name of the machine used for the run")
    parser.add_argument("--build", required=True, help="Game build version string")
    parser.add_argument("--origin", required=True, help="Origin of the logs (e.g. manual, test-run)")
    parser.add_argument("--rolemap", help="Optional path to filename→role mapping file")
    args = parser.parse_args()

    # Prepare output directory
    os.makedirs(args.outdir, exist_ok=True)
    events_path = os.path.join(args.outdir, "events.jsonl")
    metrics_path = os.path.join(args.outdir, "metrics.csv")

    rolemap = read_rolemap(args.rolemap)

    # Collect metrics per file and accumulate overall metrics across all files
    aggregated_metrics: List[Tuple[str, Dict[str, float]]] = []
    with open(events_path, "w", encoding="utf-8") as events_fh:
        for fname in sorted(os.listdir(args.indir)):
            path = os.path.join(args.indir, fname)
            if not os.path.isfile(path):
                continue
            metrics = LogMetrics()
            parse_log_file(path, metrics, events_fh)
            per_file_metrics = compute_metrics(metrics)
            aggregated_metrics.append((fname, per_file_metrics))

    # Write metrics.csv
    with open(metrics_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        # Header
        writer.writerow(["machine", "build", "origin", "source_role", "metric_id", "value"])
        for fname, metric_map in aggregated_metrics:
            role = infer_role(fname, rolemap)
            for metric_id, value in metric_map.items():
                writer.writerow([
                    args.machine,
                    args.build,
                    args.origin,
                    role,
                    metric_id,
                    f"{value:.3f}",
                ])


if __name__ == "__main__":
    main()