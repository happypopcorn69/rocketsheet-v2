# RocketSheet v2 — Log-First Performance Pipeline (SE2)

**Why:** v1 broke whenever test shapes changed. v2 ingests *all* logs first, creates a canonical event stream, then extracts metrics/views by config.

## What it does (today)

- Ingests N Space Engineers 2 logs and writes `events.jsonl`.
- Extracts load metrics (`LOADING_TIME|…`) and `AGGREGATE_*` blocks.
- (If present) derives frametime p50/p95 from `Perf: FPS=…`.
- Emits a tidy `metrics.csv` tagged with `machine`, `build`, `origin`, `source_role`.

## Quick start

```bash
python scripts/ingest_v2.py \
  --in runs/TEST_A \
  --out out/TEST_A \
  --machine "minimal AMD3" \
  --build "2.0.1.2559" \
  --origin manual
```

### Classifying client/server/dedicated

The ingestor infers role from filename:

* contains `client` → `client`
* contains `server` (not client) → `server`
* contains `dedicated` → `dedicated`
  Else → `unknown`

Rename your files or provide a simple map:

```
# rolemap.txt
output.log=client
headless.log=server
```

Run with:

```bash
python scripts/ingest_v2.py ... --rolemap rolemap.txt
```

## Outputs

* `out/TEST_A/events.jsonl` — every log line preserved + any parsed `kv`.
* `out/TEST_A/metrics.csv` — columns:

  ```
  machine,build,origin,source_role,metric_id,value
  ```

  (After scenario patch, a `scenario` column is added.)

## Current limits

* Scenario is not yet a first‑class column (next patch).
* No SQLite/Parquet emitter yet (planned).
* Pattern pack is minimal; v2 uses built‑in regex for core lines.

## Roadmap

* [ ] **Scenario tagging:** add `scenario` (from `LOADING_BEGIN|X`/`LOADING_TIME|X`)
* [ ] **Per‑scenario frametime:** slice FPS samples between `BEGIN X` → `TIME X`
* [ ] **Role mapping file:** `--rolemap` (basic support)
* [ ] **SQLite emitter:** quick queries + RocketSheet pivots
* [ ] **Coverage gate:** parse coverage, determinism checks, mixed‑build warnings
* [ ] **Config‑driven extractors:** move v2 metrics into YAML
