#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adaptateur IEBCS pour exécuter la simulation à partir de frames RGB et de timestamps."""
import argparse, json, sys
from pathlib import Path
import numpy as np
import cv2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--frames", required=True)
    ap.add_argument("--timestamps_us", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--params_json", required=True)
    args = ap.parse_args()

    repo = Path(args.repo)
    sys.path.insert(0, str(repo / "src"))

    from dvs_sensor import DvsSensor
    from event_buffer import EventBuffer

    params = json.loads(Path(args.params_json).read_text())
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    frames = sorted(Path(args.frames).glob("*.png"))
    ts_us = [int(float(x.strip())) for x in Path(args.timestamps_us).read_text().splitlines() if x.strip()]
    if len(frames) < 2:
        raise RuntimeError("IEBCS: pas assez de frames.")
    ts_us = ts_us[:len(frames)]

    first = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
    if first is None:
        raise RuntimeError("IEBCS: première frame illisible.")
    h, w = first.shape[:2]

    dvs = DvsSensor("pipeline_sensor")
    dvs.initCamera(
        int(w), int(h),
        lat=float(params["latency_us"]),
        jit=float(params["jitter_us"]),
        ref=float(params["refractory_us"]),
        tau=float(params["tau_us"]),
        th_pos=float(params["th_pos"]),
        th_neg=float(params["th_neg"]),
        th_noise=float(params["th_noise"]),
        bgnp=float(params["bgn_pos_hz"]),
        bgnn=float(params["bgn_neg_hz"]),
    )

    if params.get("use_measured_noise"):
        pos = repo / params.get("noise_pos_file", "data/noise_pos_161lux.npy")
        neg = repo / params.get("noise_neg_file", "data/noise_neg_161lux.npy")
        if pos.exists() and neg.exists():
            dvs.init_bgn_hist(str(pos), str(neg))

    def to_flux(img):
        luv_l = cv2.cvtColor(img, cv2.COLOR_BGR2LUV)[:, :, 0]
        return luv_l.astype(np.float64) / 255.0 * float(params.get("lux_scale", 10000.0))

    dvs.init_image(to_flux(first))
    ev_full = EventBuffer(1)

    for i in range(1, len(frames)):
        img = cv2.imread(str(frames[i]), cv2.IMREAD_COLOR)
        if img is None:
            continue
        dt = max(1, int(ts_us[i] - ts_us[i-1]))
        ev = dvs.update(to_flux(img), dt)
        if ev is not None:
            ev_full.increase_ev(ev)

    ev_full.sort()
    dat_path = outdir / "events.dat"
    txt_path = outdir / "events.txt"
    ev_full.write(str(dat_path), width=w, height=h)

    arr = np.column_stack([
        ev_full.get_ts().astype(np.int64),
        ev_full.get_x().astype(np.int64),
        ev_full.get_y().astype(np.int64),
        ev_full.get_p().astype(np.int64),
    ])
    np.savetxt(txt_path, arr, fmt="%d", header="t_us x y p")
    print(f"IEBCS wrote {arr.shape[0]} events to {txt_path} and {dat_path}")

if __name__ == "__main__":
    main()
