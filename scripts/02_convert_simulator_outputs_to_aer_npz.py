#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convertit les sorties brutes des simulateurs vers un format AER commun.

Chaque simulateur ecrit ses evenements avec ses propres fichiers, unites de temps
et conventions de polarite. Ce script centralise cette normalisation pour obtenir
un `.npz` comparable: `x`, `y`, `t` en secondes et `p` avec 0=OFF, 1=ON.
"""
from __future__ import annotations

# La liste sert a garder un ordre stable et a eviter de parcourir des dossiers non prevus.

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

# Unites documentees/controlees par simulateur. On evite le mode auto pour ne
# pas baser la comparaison sur une estimation d ordre de grandeur.
SIMULATOR_TIME_UNITS = {
    "v2e": "s",
    "vid2e": "s",
    "iebcs": "us",
    "dvs_voltmeter": "us",
    "pix2nvs": "us",
}

TEXT_EVENT_ORDERS = {
    "v2e": "t x y p",
    "vid2e": "t x y p",
    "iebcs": "t x y p",
    "dvs_voltmeter": "t x y p",
    "pix2nvs": "x y t p",
}

ARRAY_EVENT_ORDERS = {
    "v2e": "x y t p",
    "vid2e": "t x y p",
    "iebcs": "t x y p",
    "dvs_voltmeter": "t x y p",
    "pix2nvs": "x y t p",
}

VALID_TIME_UNITS = {"s", "ms", "us", "ns"}

# Structure interne: elle garde les tableaux d evenements et quelques informations sur leur origine.
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
    input_len_x: int
    input_len_y: int
    input_len_t: int
    input_len_p: int
    aligned_len: int
    truncated_events: int
    invalid_events_removed: int
    sorted_by_time: bool
    non_monotonic_before_sort: bool


def eprint(*args, **kwargs) -> None:
    print(*args, file=sys.stderr, **kwargs)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

# Normalisation scientifique: polarite et temps doivent avoir la meme convention avant toute comparaison.
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


def convert_time_to_seconds(t: np.ndarray, unit: str) -> Tuple[np.ndarray, str]:
    """Convertit les timestamps vers les secondes avec une unite explicite."""
    t = np.asarray(t, dtype=np.float64)
    if t.size == 0:
        return t, unit

    unit = unit.lower()
    if unit in ["s", "sec", "second", "seconds"]:
        return t, "s"
    if unit in ["ms", "millisecond", "milliseconds"]:
        return t / 1e3, "ms"
    if unit in ["us", "?s", "microsecond", "microseconds"]:
        return t / 1e6, "us"
    if unit in ["ns", "nanosecond", "nanoseconds"]:
        return t / 1e9, "ns"

    raise ValueError(f"Unknown explicit time unit: {unit}")


def time_unit_for(simulator: str, args: argparse.Namespace) -> str:
    # L'unite vient d'abord de la table documentee. Un override CLI reste possible,
    # mais il doit etre explicite, par exemple --time-unit v2e=s.
    return args.time_units.get(simulator, SIMULATOR_TIME_UNITS[simulator])


def split_event_columns(arr: np.ndarray, order: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    """Rearrange un tableau Nx4 selon un ordre documente, sans detection auto."""
    if arr.ndim != 2 or arr.shape[1] < 4:
        raise ValueError("Need an Nx4 array to split event columns")

    order_norm = " ".join(order.lower().replace(",", " ").split())
    cols = {name: arr[:, idx] for idx, name in enumerate(order_norm.split())}
    required = {"x", "y", "t", "p"}
    if not required.issubset(cols):
        raise ValueError(f"Unsupported documented event order: {order}")
    return cols["x"], cols["y"], cols["t"], cols["p"], order_norm


# Nettoyage commun: on aligne les longueurs, on retire les valeurs invalides et on trie par temps.
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

    input_len_x = len(x)
    input_len_y = len(y)
    input_len_t = len(t)
    input_len_p = len(p)
    n = min(input_len_x, input_len_y, input_len_t, input_len_p)
    truncated_events = max(input_len_x, input_len_y, input_len_t, input_len_p) - n
    x, y, t, p = x[:n], y[:n], t[:n], p[:n]

    non_monotonic_before_sort = bool(t.size > 1 and np.any(np.diff(t) < 0))

    xf = x.astype(np.float64, copy=False)
    yf = y.astype(np.float64, copy=False)
    mask = np.isfinite(t) & np.isfinite(xf) & np.isfinite(yf) & (xf >= 0) & (yf >= 0)
    invalid_events_removed = int(n - np.count_nonzero(mask))
    x, y, t, p = x[mask], y[mask], t[mask], p[mask]

    sorted_by_time = bool(sort_by_time and non_monotonic_before_sort)
    if sorted_by_time:
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
        input_len_x=int(input_len_x),
        input_len_y=int(input_len_y),
        input_len_t=int(input_len_t),
        input_len_p=int(input_len_p),
        aligned_len=int(n),
        truncated_events=int(truncated_events),
        invalid_events_removed=invalid_events_removed,
        sorted_by_time=sorted_by_time,
        non_monotonic_before_sort=non_monotonic_before_sort,
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
        "input_len_x": events.input_len_x,
        "input_len_y": events.input_len_y,
        "input_len_t": events.input_len_t,
        "input_len_p": events.input_len_p,
        "aligned_len": events.aligned_len,
        "truncated_events": events.truncated_events,
        "invalid_events_removed": events.invalid_events_removed,
        "sorted_by_time": events.sorted_by_time,
        "non_monotonic_before_sort": events.non_monotonic_before_sort,
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

# Lecteurs de fichiers: chaque bloc lit un format brut different, puis renvoie le meme objet Events.
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
    arr = _parse_numeric_event_lines(path, min_cols=4)
    x, y, t_raw, p, order_norm = split_event_columns(arr, order)
    t, used_unit = convert_time_to_seconds(t_raw, time_unit)
    return clean_events(x, y, t, p, str(path), "txt", order_norm, used_unit)



# Les fichiers NPZ peuvent contenir des noms de tableaux differents selon le simulateur.
def read_npz_events(path: Path, simulator: str, time_unit: str) -> Events:
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
        x, y, t_raw, p, order_norm = split_event_columns(arr[:, :4], ARRAY_EVENT_ORDERS[simulator])
        raw_order = f"events: {order_norm}"
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

# Lecture HDF5: utile notamment pour les sorties v2e qui sauvegardent souvent les evenements en h5.
def read_h5_events(path: Path, simulator: str, time_unit: str) -> Events:
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
            x, y, t_raw, p, order_norm = split_event_columns(arr[:, :4], ARRAY_EVENT_ORDERS[simulator])
            t, used_unit = convert_time_to_seconds(t_raw, time_unit)
            return clean_events(x, y, t, p, str(path), "h5", f"{key}: {order_norm}", used_unit)

    raise ValueError(f"{path}: no recognizable event datasets found in h5 file")

# Lecture DAT IEBCS: on decode le format binaire quand le txt n est pas disponible.
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

# Decouverte des fichiers: on cherche les candidats dans une structure par simulateur et sequence.
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
    unit = time_unit_for(simulator, args)

    if suffix == ".npz":
        return read_npz_events(path, simulator=simulator, time_unit=unit)
    if suffix in [".h5", ".hdf5"]:
        return read_h5_events(path, simulator=simulator, time_unit=unit)
    if suffix == ".dat":
        if simulator != "iebcs":
            raise ValueError(f"{path}: .dat reader is implemented for ICNS/IEBCS only")
        return read_dat_event_icns(path)
    if suffix == ".txt":
        return read_txt_events(path, order=TEXT_EVENT_ORDERS[simulator], time_unit=unit)

    raise ValueError(f"Unsupported candidate file: {path}")

# Conversion d une sequence: on choisit le meilleur candidat lisible puis on sauvegarde NPZ + metadata.
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
        "input_len_x": events.input_len_x,
        "input_len_y": events.input_len_y,
        "input_len_t": events.input_len_t,
        "input_len_p": events.input_len_p,
        "aligned_len": events.aligned_len,
        "truncated_events": events.truncated_events,
        "invalid_events_removed": events.invalid_events_removed,
        "sorted_by_time": events.sorted_by_time,
        "non_monotonic_before_sort": events.non_monotonic_before_sort,
        "duration_s": float(events.t[-1] - events.t[0]) if events.t.size > 1 else 0.0,
        "num_on": int(np.sum(events.p == 1)),
        "num_off": int(np.sum(events.p == 0)),
        "raw_order": events.raw_order,
        "raw_format": events.raw_format,
        "time_unit_in": events.time_unit_in,
    }

# Le CSV de resume sert a verifier rapidement quelles sequences ont ete converties ou ignorees.
def write_summary_csv(rows: List[Dict[str, object]], out_file: Path) -> None:
    ensure_dir(out_file.parent)
    fieldnames = [
        "simulator", "sequence", "status", "source_file", "output_npz",
        "num_events", "input_len_x", "input_len_y", "input_len_t", "input_len_p",
        "aligned_len", "truncated_events", "invalid_events_removed",
        "sorted_by_time", "non_monotonic_before_sort",
        "duration_s", "num_on", "num_off",
        "raw_format", "raw_order", "time_unit_in", "error"
    ]
    with out_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})

# Interface CLI: les chemins restent explicites pour que le script soit simple a relancer sous Linux.
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
    parser.add_argument("--time-unit", action="append", default=[], metavar="SIM=UNIT",
                        help="Override an explicit simulator time unit, e.g. v2e=s or pix2nvs=us.")
    parser.add_argument("--strict", action="store_true", help="Stop on first error.")
    parser.add_argument("--verbose", action="store_true", help="Print detailed warnings.")
    return parser.parse_args()


def parse_time_unit_overrides(values: Sequence[str]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --time-unit value '{value}'. Expected SIM=UNIT.")
        simulator, unit = [part.strip().lower() for part in value.split("=", 1)]
        if simulator not in SIMULATORS:
            raise ValueError(f"Unknown simulator in --time-unit: {simulator}")
        if unit not in VALID_TIME_UNITS:
            raise ValueError(f"Unknown unit for {simulator}: {unit}. Expected one of {sorted(VALID_TIME_UNITS)}")
        overrides[simulator] = unit
    return overrides


def main() -> int:
    args = parse_args()
    try:
        args.time_units = parse_time_unit_overrides(args.time_unit)
    except ValueError as exc:
        eprint(f"[ERROR] {exc}")
        return 2
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
