#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
convert_simulator_outputs_to_npz.py

Convertit les sorties brutes des simulateurs video-to-event vers un format AER unifié :
    x, y, t, p

Convention de sortie :
    x : np.uint16
    y : np.uint16
    t : np.float64, en secondes
    p : np.uint8, 0 = OFF, 1 = ON

Structure de sortie :
    OUT_ROOT/
      v2e/<sequence>.npz
      vid2e/<sequence>.npz
      iebcs/<sequence>.npz
      dvs_voltmeter/<sequence>.npz
      pix2nvs/<sequence>.npz

Usage :
    python convert_simulator_outputs_to_npz.py \
      --sim-root runs/simulated_events \
      --out-root runs/aer_npz \
      --overwrite
"""

from __future__ import annotations

# Convertit les sorties des simulateurs vers le format NPZ AER commun.

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

SIMULATORS = ["v2e", "vid2e", "iebcs", "dvs_voltmeter", "pix2nvs"]


@dataclass
class Events:
    x: np.ndarray
    y: np.ndarray
    t: np.ndarray
    p: np.ndarray
    source_file: str
    raw_format: str
    raw_order: str
    time_unit_in: str


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_polarity(p: np.ndarray) -> np.ndarray:
    """Convention unifiée : 0 = OFF, 1 = ON.

    Cas importants rencontrés pendant le stage :
      - {0, 1}      : déjà correct
      - {-1, 1}     : -1 = OFF, 1 = ON
      - {1, 255}    : uint8(-1) = 255, donc 255 = OFF et 1 = ON
    """
    p = np.asarray(p)
    if p.size == 0:
        return p.astype(np.uint8)

    if np.issubdtype(p.dtype, np.floating):
        valid = p[np.isfinite(p)]
    else:
        valid = p

    vals = set(np.unique(valid).astype(np.int64).tolist())

    if vals.issubset({0, 1}):
        return p.astype(np.uint8)
    if vals.issubset({-1, 1}):
        return (p > 0).astype(np.uint8)
    if vals.issubset({1, 255}):
        return (p == 1).astype(np.uint8)
    if 255 in vals:
        return ((p != 255) & (p > 0)).astype(np.uint8)

    return (p > 0).astype(np.uint8)


def convert_time_to_seconds(t: np.ndarray, unit: str = "auto") -> Tuple[np.ndarray, str]:
    """
    Convertit les timestamps vers les secondes.
    unit = s, ms, us, ns ou auto.
    """
    t = np.asarray(t, dtype=np.float64)
    if t.size == 0:
        return t, unit

    unit = unit.lower()
    if unit in ["s", "sec", "second", "seconds"]:
        return t, "s"
    if unit in ["ms", "millisecond", "milliseconds"]:
        return t / 1e3, "ms"
    if unit in ["us", "µs", "microsecond", "microseconds"]:
        return t / 1e6, "us"
    if unit in ["ns", "nanosecond", "nanoseconds"]:
        return t / 1e9, "ns"
    if unit != "auto":
        raise ValueError(f"Unknown time unit: {unit}")

    max_abs = float(np.nanmax(np.abs(t)))
    if max_abs > 1e9:
        return t / 1e9, "ns(auto)"
    if max_abs > 1e4:
        return t / 1e6, "us(auto)"
    if max_abs > 1e2:
        return t / 1e3, "ms(auto)"
    return t, "s(auto)"


def clean_events(
    x: np.ndarray,
    y: np.ndarray,
    t: np.ndarray,
    p: np.ndarray,
    source_file: str,
    raw_format: str,
    raw_order: str,
    time_unit_in: str,
    sort_by_time: bool = True,
) -> Events:
    x = np.asarray(x)
    y = np.asarray(y)
    t = np.asarray(t, dtype=np.float64)
    p = normalize_polarity(np.asarray(p))

    n = min(len(x), len(y), len(t), len(p))
    x, y, t, p = x[:n], y[:n], t[:n], p[:n]

    xf = x.astype(np.float64, copy=False)
    yf = y.astype(np.float64, copy=False)
    mask = np.isfinite(t) & np.isfinite(xf) & np.isfinite(yf) & (xf >= 0) & (yf >= 0)
    x, y, t, p = x[mask], y[mask], t[mask], p[mask]

    if sort_by_time and t.size > 1:
        order = np.argsort(t, kind="stable")
        x, y, t, p = x[order], y[order], t[order], p[order]

    return Events(
        x=x.astype(np.uint16, copy=False),
        y=y.astype(np.uint16, copy=False),
        t=t.astype(np.float64, copy=False),
        p=p.astype(np.uint8, copy=False),
        source_file=str(source_file),
        raw_format=raw_format,
        raw_order=raw_order,
        time_unit_in=time_unit_in,
    )


def save_npz(events: Events, out_file: Path, compress: bool = False) -> None:
    ensure_dir(out_file.parent)
    writer = np.savez_compressed if compress else np.savez
    writer(out_file, x=events.x, y=events.y, t=events.t, p=events.p)


def save_metadata(events: Events, out_file: Path, simulator: str, sequence: str) -> None:
    meta = {
        "simulator": simulator,
        "sequence": sequence,
        "source_file": events.source_file,
        "raw_format": events.raw_format,
        "raw_order": events.raw_order,
        "time_unit_input": events.time_unit_in,
        "time_unit_output": "s",
        "polarity_output": "0=OFF, 1=ON",
        "num_events": int(events.t.size),
        "duration_s": float(events.t[-1] - events.t[0]) if events.t.size > 1 else 0.0,
        "t_min_s": float(events.t[0]) if events.t.size else None,
        "t_max_s": float(events.t[-1]) if events.t.size else None,
        "x_min": int(events.x.min()) if events.x.size else None,
        "x_max": int(events.x.max()) if events.x.size else None,
        "y_min": int(events.y.min()) if events.y.size else None,
        "y_max": int(events.y.max()) if events.y.size else None,
        "num_on": int(np.sum(events.p == 1)) if events.p.size else 0,
        "num_off": int(np.sum(events.p == 0)) if events.p.size else 0,
    }
    out_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


                                                                       
              
                                                                       

def _parse_numeric_event_lines(path: Path, min_cols: int = 4) -> np.ndarray:
    rows: List[List[float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("%"):
                continue
            s = s.replace(",", " ").replace(";", " ").replace("\t", " ")
            parts = [x for x in s.split(" ") if x]
            vals: List[float] = []
            ok = True
            for part in parts[:min_cols]:
                try:
                    vals.append(float(part))
                except ValueError:
                    ok = False
                    break
            if ok and len(vals) >= min_cols:
                rows.append(vals[:min_cols])
    if not rows:
        raise ValueError(f"No numeric event rows found in {path}")
    return np.asarray(rows, dtype=np.float64)


def read_txt_events(path: Path, order: str, time_unit: str) -> Events:
    """
    order :
      - "t x y p"
      - "x y t p"
      - "auto"
    """
    arr = _parse_numeric_event_lines(path, min_cols=4)
    order_norm = " ".join(order.lower().replace(",", " ").split())

    if order_norm == "t x y p":
        t_raw, x, y, p = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    elif order_norm == "x y t p":
        x, y, t_raw, p = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    elif order_norm == "auto":
        x, y, t_raw, p, detected = infer_txt_columns(arr)
        order_norm = detected
    else:
        raise ValueError(f"Unsupported text order '{order}'.")

    t, used_unit = convert_time_to_seconds(t_raw, time_unit)
    return clean_events(x, y, t, p, str(path), "txt", order_norm, used_unit)


def infer_txt_columns(arr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    if arr.shape[1] < 4:
        raise ValueError("Need at least 4 columns for auto detection")

    p_col = 3
    best_score = -1.0
    for c in range(4):
        vals = arr[:, c]
        score = np.mean(np.isin(np.round(vals).astype(int), [-1, 0, 1]))
        if score > best_score:
            best_score = score
            p_col = c

    remaining = [c for c in range(4) if c != p_col]
    best_t_col = remaining[0]
    best_tuple = (-1.0, -1.0)
    for c in remaining:
        vals = arr[:, c]
        monotonic_score = np.mean(np.diff(vals) >= 0) if len(vals) > 1 else 1.0
        dyn = float(np.nanmax(vals) - np.nanmin(vals))
        score_tuple = (monotonic_score, dyn)
        if score_tuple > best_tuple:
            best_tuple = score_tuple
            best_t_col = c

    xy_cols = [c for c in remaining if c != best_t_col]
    x_col, y_col = xy_cols[0], xy_cols[1]
    detected = f"auto: col{x_col}=x col{y_col}=y col{best_t_col}=t col{p_col}=p"
    return arr[:, x_col], arr[:, y_col], arr[:, best_t_col], arr[:, p_col], detected


                                                                       
             
                                                                       

def read_npz_events(path: Path, simulator: str, time_unit: str = "auto") -> Events:
    data = np.load(path, allow_pickle=False)
    keys = set(data.files)

    if {"x", "y", "t", "p"}.issubset(keys):
        x, y, t_raw, p = data["x"], data["y"], data["t"], data["p"]
        raw_order = "x y t p"
    elif {"xs", "ys", "ts", "ps"}.issubset(keys):
        x, y, t_raw, p = data["xs"], data["ys"], data["ts"], data["ps"]
        raw_order = "xs ys ts ps"
    elif "events" in keys:
        arr = np.asarray(data["events"])
        if arr.ndim != 2 or arr.shape[1] < 4:
            raise ValueError(f"{path}: dataset 'events' must be Nx4")
        if simulator in ["vid2e", "dvs_voltmeter", "iebcs"]:
            t_raw, x, y, p = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
            raw_order = "events: t x y p"
        elif simulator == "pix2nvs":
            x, y, t_raw, p = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
            raw_order = "events: x y t p"
        else:
            x, y, t_raw, p, detected = infer_txt_columns(arr[:, :4].astype(np.float64))
            raw_order = detected
    else:
        raise ValueError(f"{path}: unsupported npz keys: {sorted(keys)}")

    t, used_unit = convert_time_to_seconds(t_raw, time_unit)
    return clean_events(x, y, t, p, str(path), "npz", raw_order, used_unit)


                                                                       
                   
                                                                       

def _require_h5py():
    try:
        import h5py                
        return h5py
    except ImportError as exc:
        raise ImportError("h5py is required to read .h5 files. Install it with: pip install h5py") from exc


def _collect_h5_datasets(h5_obj) -> Dict[str, np.ndarray]:
    out: Dict[str, np.ndarray] = {}
    import h5py                

    def visit(name, obj):
        if isinstance(obj, h5py.Dataset):
            out[name.strip("/")] = obj[()]

    h5_obj.visititems(visit)
    return out


def _find_dataset_by_names(datasets: Dict[str, np.ndarray], names: Sequence[str]) -> Optional[np.ndarray]:
    for name in names:
        for key, value in datasets.items():
            if Path(key).name == name or key.endswith("/" + name):
                return value
    return None


def read_h5_events(path: Path, time_unit: str = "auto") -> Events:
    h5py = _require_h5py()
    with h5py.File(path, "r") as f:
        datasets = _collect_h5_datasets(f)

    x = _find_dataset_by_names(datasets, ["x", "xs"])
    y = _find_dataset_by_names(datasets, ["y", "ys"])
    t_raw = _find_dataset_by_names(datasets, ["t", "ts", "timestamp", "timestamps"])
    p = _find_dataset_by_names(datasets, ["p", "ps", "pol", "polarity", "polarities"])

    if x is not None and y is not None and t_raw is not None and p is not None:
        t, used_unit = convert_time_to_seconds(t_raw, time_unit)
        return clean_events(x, y, t, p, str(path), "h5", "x/y/t/p datasets", used_unit)

    for key, value in datasets.items():
        arr = np.asarray(value)
        if arr.ndim == 2 and arr.shape[1] >= 4:
            x, y, t_raw, p, detected = infer_txt_columns(arr[:, :4].astype(np.float64))
            t, used_unit = convert_time_to_seconds(t_raw, time_unit)
            return clean_events(x, y, t, p, str(path), "h5", f"{key}: {detected}", used_unit)

    raise ValueError(f"{path}: no recognizable event datasets found in h5 file")


                                                                       
                             
                                                                       

def read_dat_event_icns(path: Path) -> Events:
    with path.open("rb") as f:
        header_bytes = b""
        last_pos = f.tell()
        line = f.readline()
        while line and len(line) > 0 and line[0] == 37:       
            header_bytes += line
            last_pos = f.tell()
            line = f.readline()

        f.seek(last_pos, 0)
        ev_type_b = f.read(1)
        ev_size_b = f.read(1)
        if len(ev_type_b) != 1 or len(ev_size_b) != 1:
            raise ValueError(f"{path}: invalid DAT header")

        ev_size = int(np.frombuffer(ev_size_b, dtype=np.uint8)[0])
        data_start = f.tell()
        f.seek(0, os.SEEK_END)
        data_end = f.tell()

    if ev_size <= 0:
        raise ValueError(f"{path}: invalid event size {ev_size}")

    count_uint32 = ((data_end - data_start) // ev_size) * 2
    if count_uint32 <= 0:
        raise ValueError(f"{path}: no events in DAT file")

    data = np.fromfile(path, dtype=np.uint32, count=count_uint32, offset=data_start)
    ts = data[::2]
    packed = data[1::2]

    header_str = header_bytes.decode("utf-8", errors="ignore")
    version_match = re.search(r"Version\s+(\d+)", header_str)
    version = int(version_match.group(1)) if version_match else 0

    if version >= 2:
        x_mask = np.uint32(0x00007FF)
        y_mask = np.uint32(0x0FFFC000)
        pol_mask = np.uint32(0x10000000)
        x_shift, y_shift, pol_shift = 0, 14, 28
    else:
        x_mask = np.uint32(0x00001FF)
        y_mask = np.uint32(0x0001FE00)
        pol_mask = np.uint32(0x00020000)
        x_shift, y_shift, pol_shift = 0, 9, 17

    x = (packed & x_mask) >> x_shift
    y = (packed & y_mask) >> y_shift
    p = (packed & pol_mask) >> pol_shift

    t, used_unit = convert_time_to_seconds(ts, "us")
    return clean_events(x, y, t, p, str(path), "dat", "DAT: t_us + packed(x,y,p)", used_unit)


                                                                       
           
                                                                       

def is_sequence_dir(path: Path) -> bool:
    return path.is_dir() and not path.name.startswith("_")


def list_sequence_dirs(sim_dir: Path) -> List[Path]:
    if not sim_dir.exists():
        return []
    subdirs = [p for p in sorted(sim_dir.iterdir()) if is_sequence_dir(p)]
    if not subdirs:
        if any(p.suffix.lower() in [".npz", ".h5", ".hdf5", ".txt", ".dat"] for p in sim_dir.rglob("*")):
            return [sim_dir]
    return subdirs


def unique_paths(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    out = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            out.append(p)
            seen.add(rp)
    return out


def find_candidates(sequence_dir: Path, simulator: str) -> List[Path]:
    all_files = [p for p in sequence_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]

    def usable(p: Path) -> bool:
        name = p.name.lower()
        if name in ["command.json", "metadata.json", "manifest.json", "summary.txt"]:
            return False
        if "log" in name and p.suffix.lower() == ".txt":
            return False
        return True

    all_files = [p for p in all_files if usable(p)]

    if simulator == "v2e":
        preferred = []
        preferred += [p for p in all_files if p.name.lower() in ["events.npz", "dvs_events.npz"]]
        preferred += [p for p in all_files if p.suffix.lower() in [".h5", ".hdf5"]]
        preferred += [p for p in all_files if p.name.lower() in ["events.txt", "dvs_events.txt"]]
        preferred += [p for p in all_files if p.suffix.lower() == ".txt"]
        return unique_paths(preferred)

    if simulator == "vid2e":
        preferred = []
        preferred += [p for p in all_files if p.name.lower() == "events.npz"]
        preferred += [p for p in all_files if p.suffix.lower() == ".npz"]
        preferred += [p for p in all_files if p.name.lower() == "events.txt"]
        preferred += [p for p in all_files if p.suffix.lower() == ".txt"]
        return unique_paths(preferred)

    if simulator == "iebcs":
        preferred = []
        preferred += [p for p in all_files if p.name.lower() == "events.npz"]
        preferred += [p for p in all_files if p.name.lower() == "events.txt"]
        preferred += [p for p in all_files if p.name.lower() == "events.dat"]
        preferred += [p for p in all_files if p.suffix.lower() == ".dat"]
        preferred += [p for p in all_files if p.suffix.lower() == ".txt"]
        return unique_paths(preferred)

    if simulator == "dvs_voltmeter":
        preferred = []
        preferred += [p for p in all_files if p.name.lower() == "events.npz"]
        preferred += [p for p in all_files if p.suffix.lower() == ".npz"]
        preferred += [p for p in all_files if p.suffix.lower() == ".txt"]
        return unique_paths(preferred)

    if simulator == "pix2nvs":
        preferred = []
        preferred += [p for p in all_files if p.name.lower() == "events.npz"]
        preferred += [p for p in all_files if p.suffix.lower() == ".npz"]
        preferred += [p for p in all_files if "events" in [part.lower() for part in p.parts] and p.suffix.lower() == ".txt"]
        preferred += [p for p in all_files if p.suffix.lower() == ".txt"]
        return unique_paths(preferred)

    return []


def sequence_name_from_dir(seq_dir: Path, sim_dir: Path) -> str:
    return sim_dir.name if seq_dir == sim_dir else seq_dir.name


                                                                       
                             
                                                                       

def read_candidate(path: Path, simulator: str, args: argparse.Namespace) -> Events:
    suffix = path.suffix.lower()

    if suffix == ".npz":
        return read_npz_events(path, simulator=simulator, time_unit=args.auto_time_unit)
    if suffix in [".h5", ".hdf5"]:
        return read_h5_events(path, time_unit=args.auto_time_unit)
    if suffix == ".dat":
        if simulator != "iebcs":
            raise ValueError(f"{path}: .dat reader is implemented for ICNS/IEBCS only")
        return read_dat_event_icns(path)
    if suffix == ".txt":
        if simulator == "dvs_voltmeter":
            return read_txt_events(path, order="t x y p", time_unit="us")
        if simulator == "iebcs":
            return read_txt_events(path, order="t x y p", time_unit="us")
        if simulator == "pix2nvs":
            return read_txt_events(path, order="x y t p", time_unit="us")
        if simulator in ["v2e", "vid2e"]:
            return read_txt_events(path, order="auto", time_unit=args.auto_time_unit)

    raise ValueError(f"Unsupported candidate file: {path}")


def convert_one_sequence(
    simulator: str,
    sim_dir: Path,
    seq_dir: Path,
    out_root: Path,
    args: argparse.Namespace,
) -> Dict[str, object]:
    sequence = sequence_name_from_dir(seq_dir, sim_dir)
    candidates = find_candidates(seq_dir, simulator)
    if not candidates:
        raise FileNotFoundError(f"No candidate event file found for {simulator}/{sequence}")

    last_error = None
    events: Optional[Events] = None
    used_candidate: Optional[Path] = None

    for cand in candidates:
        try:
            ev = read_candidate(cand, simulator, args)
            if ev.t.size == 0:
                raise ValueError("0 events after reading")
            events = ev
            used_candidate = cand
            break
        except Exception as exc:
            last_error = exc
            if args.verbose:
                eprint(f"[WARN] {simulator}/{sequence}: failed candidate {cand}: {exc}")

    if events is None or used_candidate is None:
        raise RuntimeError(f"Could not read events for {simulator}/{sequence}. Last error: {last_error}")

    out_dir = out_root / simulator
    ensure_dir(out_dir)
    out_npz = out_dir / f"{sequence}.npz"
    out_meta = out_dir / f"{sequence}.json"

    if out_npz.exists() and not args.overwrite:
        raise FileExistsError(f"{out_npz} exists. Use --overwrite to replace it.")

    save_npz(events, out_npz, compress=args.compress)
    save_metadata(events, out_meta, simulator=simulator, sequence=sequence)

    return {
        "simulator": simulator,
        "sequence": sequence,
        "status": "ok",
        "source_file": str(used_candidate),
        "output_npz": str(out_npz),
        "num_events": int(events.t.size),
        "duration_s": float(events.t[-1] - events.t[0]) if events.t.size > 1 else 0.0,
        "num_on": int(np.sum(events.p == 1)),
        "num_off": int(np.sum(events.p == 0)),
        "raw_order": events.raw_order,
        "raw_format": events.raw_format,
        "time_unit_in": events.time_unit_in,
    }


def write_summary_csv(rows: List[Dict[str, object]], out_file: Path) -> None:
    ensure_dir(out_file.parent)
    fieldnames = [
        "simulator", "sequence", "status", "source_file", "output_npz",
        "num_events", "duration_s", "num_on", "num_off",
        "raw_format", "raw_order", "time_unit_in", "error"
    ]
    with out_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


                                                                       
     
                                                                       

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert simulator event outputs to unified AER .npz files.")
    parser.add_argument("--sim-root", type=Path, required=True,
                        help="Root folder containing raw simulator outputs, e.g. vivid_event_runs/simulated_events")
    parser.add_argument("--out-root", type=Path, required=True,
                        help="Output root folder for unified .npz files.")
    parser.add_argument("--simulators", nargs="+", default=SIMULATORS, choices=SIMULATORS,
                        help="Simulators to convert.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing .npz files.")
    parser.add_argument("--compress", action="store_true", help="Use compressed npz. Smaller but slower.")
    parser.add_argument("--auto-time-unit", default="auto", choices=["auto", "s", "ms", "us", "ns"],
                        help="Time unit for ambiguous v2e/Vid2E formats.")
    parser.add_argument("--strict", action="store_true", help="Stop on first error.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed warnings.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sim_root: Path = args.sim_root.expanduser().resolve()
    out_root: Path = args.out_root.expanduser().resolve()

    if not sim_root.exists():
        eprint(f"[ERROR] sim-root does not exist: {sim_root}")
        return 2

    ensure_dir(out_root)
    rows: List[Dict[str, object]] = []

    for simulator in args.simulators:
        sim_dir = sim_root / simulator

                                                
        ensure_dir(out_root / simulator)

        if not sim_dir.exists():
            msg = f"Simulator folder not found: {sim_dir}"
            rows.append({"simulator": simulator, "sequence": "", "status": "missing", "error": msg})
            eprint(f"[WARN] {msg}")
            if args.strict:
                write_summary_csv(rows, out_root / "conversion_summary.csv")
                return 1
            continue

        seq_dirs = list_sequence_dirs(sim_dir)
        if not seq_dirs:
            msg = f"No sequence folder or event file found in {sim_dir}"
            rows.append({"simulator": simulator, "sequence": "", "status": "empty", "error": msg})
            eprint(f"[WARN] {msg}")
            if args.strict:
                write_summary_csv(rows, out_root / "conversion_summary.csv")
                return 1
            continue

        print(f"\n[{simulator}] {len(seq_dirs)} sequence(s) found")

        for seq_dir in seq_dirs:
            seq_name = sequence_name_from_dir(seq_dir, sim_dir)
            try:
                row = convert_one_sequence(simulator, sim_dir, seq_dir, out_root, args)
                rows.append(row)
                rel = Path(str(row["output_npz"])).relative_to(out_root)
                print(f"  OK {seq_name}: {row['num_events']} events -> {rel}")
            except Exception as exc:
                msg = str(exc)
                rows.append({"simulator": simulator, "sequence": seq_name, "status": "error", "error": msg})
                eprint(f"  [ERROR] {simulator}/{seq_name}: {msg}")
                if args.strict:
                    write_summary_csv(rows, out_root / "conversion_summary.csv")
                    return 1

    write_summary_csv(rows, out_root / "conversion_summary.csv")
    print("\nDone.")
    print(f"Unified AER npz root: {out_root}")
    print(f"Summary: {out_root / 'conversion_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
