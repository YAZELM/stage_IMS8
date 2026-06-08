#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Prepare les evenements DVS reels ViViD++ au format AER commun.

Les evenements reels servent de reference dans la comparaison. Ce script assemble
les fragments `.npz` d une sequence, remet le temps a zero et sauvegarde un seul
fichier `vivid/<sequence>.npz` comparable aux sorties des simulateurs.
"""
from __future__ import annotations

# Prépare les événements réels ViViD++ au même format que les simulations.

import argparse
import csv
import math
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from numpy.lib.format import open_memmap


def write_csv(path: Path, rows: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

# Comme pour les simulateurs, le temps et la polarite sont normalises avant la sauvegarde finale.
def time_to_seconds(t: np.ndarray, unit: str) -> np.ndarray:
    # Les fragments produits par dataset_pipeline utilisent t en secondes.
    # Si un autre export VIVID est utilise, l'unité doit etre indiquee explicitement.
    t = np.asarray(t, dtype=np.float64)
    unit = unit.lower()
    if unit == "s":
        return t
    if unit == "ms":
        return t * 1e-3
    if unit == "us":
        return t * 1e-6
    if unit == "ns":
        return t * 1e-9
    raise ValueError(f"Unknown explicit time unit: {unit}")


def normalize_polarity(p: np.ndarray) -> np.ndarray:
    """Ramene la polarite vers 0=OFF et 1=ON, quelle que soit la convention lue."""
    p = np.asarray(p)
    if p.size == 0:
        return p.astype(np.uint8)
    vals = set(np.unique(p).astype(np.int64).tolist())

    if vals.issubset({1, 255}):
        return (p == 1).astype(np.uint8)
    if vals.issubset({0, 1}):
        return p.astype(np.uint8)
    if vals.issubset({-1, 1}):
        return (p > 0).astype(np.uint8)
    if 255 in vals:
        return ((p != 255) & (p > 0)).astype(np.uint8)
    return (p > 0).astype(np.uint8)



# Chargement d un fragment: on accepte plusieurs schemas et on renvoie toujours x,y,t,p.
def load_events_npz(path: Path, unit: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Dict]:
    data = np.load(path, allow_pickle=False)
    keys = set(data.files)

    if {"x", "y", "t", "p"}.issubset(keys):
        x, y, t, p = data["x"], data["y"], data["t"], data["p"]
        fmt = "keys:x,y,t,p"
    elif {"xs", "ys", "ts", "ps"}.issubset(keys):
        x, y, t, p = data["xs"], data["ys"], data["ts"], data["ps"]
        fmt = "keys:xs,ys,ts,ps"
    else:
        raise ValueError(
            f"no explicit VIVID AER arrays found in {path}; "
            f"expected x,y,t,p or xs,ys,ts,ps, got keys={data.files}"
        )

    x = np.asarray(x).astype(np.int32, copy=False).ravel()
    y = np.asarray(y).astype(np.int32, copy=False).ravel()
    t = time_to_seconds(np.asarray(t).ravel(), unit)
    p = normalize_polarity(np.asarray(p).ravel())

    n = min(len(x), len(y), len(t), len(p))
    x, y, t, p = x[:n], y[:n], t[:n], p[:n]

    valid = np.isfinite(t) & (x >= 0) & (y >= 0)
    x, y, t, p = x[valid], y[valid], t[valid], p[valid]

    if len(t) > 1 and np.any(np.diff(t) < 0):
        order = np.argsort(t)
        x, y, t, p = x[order], y[order], t[order], p[order]

    rep = {
        "file": str(path),
        "keys": ",".join(data.files),
        "format": fmt,
        "n_events": int(len(t)),
        "t_min_s": float(np.min(t)) if len(t) else float("nan"),
        "t_max_s": float(np.max(t)) if len(t) else float("nan"),
        "x_min": int(np.min(x)) if len(x) else -1,
        "x_max": int(np.max(x)) if len(x) else -1,
        "y_min": int(np.min(y)) if len(y) else -1,
        "y_max": int(np.max(y)) if len(y) else -1,
        "p_unique_after": ",".join(map(str, np.unique(p).tolist())) if len(p) else "",
        "n_on": int(np.sum(p == 1)),
        "n_off": int(np.sum(p == 0)),
    }
    return x, y, t, p, rep

# Decouverte des sequences VIVID: chaque dossier sequence peut contenir plusieurs fragments NPZ.
def discover(vivid_root: Path) -> Dict[str, List[Path]]:
    out = {}
    for seq_dir in sorted(vivid_root.iterdir()):
        ev_dir = seq_dir / "events"
        if seq_dir.is_dir() and ev_dir.exists():
            files = sorted(ev_dir.glob("*.npz"))
            if files:
                out[seq_dir.name] = files
    return out

# Assemblage d une sequence: on utilise des memmaps pour limiter la memoire sur les gros fichiers.
def convert_sequence(seq: str, fragments: List[Path], out_file: Path, tmp_dir: Path, unit: str, overwrite: bool, sort_final: bool):
    frag_rows, err_rows = [], []
    if out_file.exists() and not overwrite:
        return {"sequence": seq, "status": "skipped_exists", "out_file": str(out_file)}, frag_rows, err_rows


    total = 0
    t_min, t_max = math.inf, -math.inf
    x_max, y_max = -1, -1
    n_on, n_off = 0, 0
    valid_frags = []

    for f in fragments:
        try:
            x, y, t, p, rep = load_events_npz(f, unit)
            rep["sequence"] = seq
            frag_rows.append(rep)
            if len(t):
                valid_frags.append(f)
                total += len(t)
                t_min = min(t_min, float(np.min(t)))
                t_max = max(t_max, float(np.max(t)))
                x_max = max(x_max, int(np.max(x)))
                y_max = max(y_max, int(np.max(y)))
                n_on += int(np.sum(p == 1))
                n_off += int(np.sum(p == 0))
        except Exception as e:
            err_rows.append({"sequence": seq, "file": str(f), "error": str(e)})

    if total == 0:
        return {"sequence": seq, "status": "failed_no_events", "n_fragments": len(fragments), "out_file": str(out_file)}, frag_rows, err_rows

    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    x_tmp = tmp_dir / f"{seq}.x.npy"
    y_tmp = tmp_dir / f"{seq}.y.npy"
    t_tmp = tmp_dir / f"{seq}.t.npy"
    p_tmp = tmp_dir / f"{seq}.p.npy"

    x_mm = open_memmap(x_tmp, mode="w+", dtype=np.int32, shape=(total,))
    y_mm = open_memmap(y_tmp, mode="w+", dtype=np.int32, shape=(total,))
    t_mm = open_memmap(t_tmp, mode="w+", dtype=np.float64, shape=(total,))
    p_mm = open_memmap(p_tmp, mode="w+", dtype=np.uint8, shape=(total,))

    pos = 0
    for f in valid_frags:
        x, y, t, p, _ = load_events_npz(f, unit)
        n = len(t)
        x_mm[pos:pos+n] = x
        y_mm[pos:pos+n] = y
        t_mm[pos:pos+n] = t - t_min
        p_mm[pos:pos+n] = p
        pos += n

    if sort_final:

        order = np.argsort(t_mm)
        np.savez_compressed(out_file, x=x_mm[order], y=y_mm[order], t=t_mm[order], p=p_mm[order])
    else:

        np.savez_compressed(out_file, x=np.asarray(x_mm), y=np.asarray(y_mm), t=np.asarray(t_mm), p=np.asarray(p_mm))

    for f in (x_tmp, y_tmp, t_tmp, p_tmp):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass

    duration = t_max - t_min
    summary = {
        "sequence": seq,
        "status": "ok",
        "out_file": str(out_file),
        "n_fragments": len(fragments),
        "n_valid_fragments": len(valid_frags),
        "n_events": int(total),
        "n_on": int(n_on),
        "n_off": int(n_off),
        "on_ratio": n_on / total if total else float("nan"),
        "duration_s": duration,
        "density_events_s": total / duration if duration > 0 else float("nan"),
        "t_start_after_normalization": 0.0,
        "t_end_after_normalization": duration,
        "x_max": x_max,
        "y_max": y_max,
        "format_out": "x,y,t,p ; t_seconds ; p_0_OFF_1_ON",
    }
    return summary, frag_rows, err_rows

# Interface CLI: on produit le dossier vivid/ et trois rapports de controle.
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vivid-root", type=Path, default=Path("./data/outputs"))
    ap.add_argument("--aer-npz-root", type=Path, default=Path("./runs/aer_npz"))
    ap.add_argument("--time-unit", choices=["s", "ms", "us", "ns"], default="s")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--sort-final", action="store_true", help="Sort final events by timestamp. More rigorous but uses more memory.")
    args = ap.parse_args()

    out_dir = args.aer_npz_root / "vivid"
    tmp_dir = args.aer_npz_root / "_tmp_vivid"
    out_dir.mkdir(parents=True, exist_ok=True)

    seqs = discover(args.vivid_root)
    if not seqs:
        print(f"[ERROR] No NPZ found in {args.vivid_root}/<sequence>/events/*.npz")
        return 1

    print(f"[INFO] Found {len(seqs)} ViViD++ sequences")
    print(f"[INFO] Output: {out_dir}")

    conv_rows, frag_rows, err_rows = [], [], []
    for seq, files in seqs.items():
        print(f"[SEQ] {seq}: {len(files)} fragment(s)")
        summary, frags, errs = convert_sequence(
            seq=seq,
            fragments=files,
            out_file=out_dir / f"{seq}.npz",
            tmp_dir=tmp_dir,
            unit=args.time_unit,
            overwrite=args.overwrite,
            sort_final=args.sort_final,
        )
        conv_rows.append(summary)
        frag_rows.extend(frags)
        err_rows.extend(errs)

        if summary.get("status") == "ok":
            print(f"  [OK] {seq}.npz | N={summary['n_events']} | ON_ratio={summary['on_ratio']:.4f} | duration={summary['duration_s']:.3f}s")
        else:
            print(f"  [WARN] {summary.get('status')}")

    write_csv(args.aer_npz_root / "vivid_conversion_report.csv", conv_rows)
    write_csv(args.aer_npz_root / "vivid_fragment_report.csv", frag_rows)
    write_csv(args.aer_npz_root / "vivid_load_errors.csv", err_rows)

    try:
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
    except Exception:
        pass

    print("\n[DONE]")
    print(f"Unified real events: {out_dir}")
    print(f"Report: {args.aer_npz_root / 'vivid_conversion_report.csv'}")
    print(f"Fragments: {args.aer_npz_root / 'vivid_fragment_report.csv'}")
    print(f"Errors: {args.aer_npz_root / 'vivid_load_errors.csv'}")
    print("\nExpected final structure:")
    print(f"{args.aer_npz_root}/")
    print("├── vivid/")
    print("│   └── <sequence>.npz")
    print("├── v2e/")
    print("├── vid2e/")
    print("├── iebcs/")
    print("├── dvs_voltmeter/")
    print("└── pix2nvs/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
