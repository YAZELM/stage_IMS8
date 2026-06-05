#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lance Vid2E/esim_py sur une sequence de frames deja preparee.

Le wrapper garde une interface simple pour la pipeline principale: frames RGB,
timestamps en secondes et sortie NPZ au format AER `x,y,t,p`. Il ne modifie pas
les images; il ne fait que transmettre les parametres de simulation a esim_py.
"""

import argparse
from pathlib import Path
import numpy as np


def save_events_npz(out_path, events):
    """
    esim_py renvoie généralement un tableau Nx4.
    L'ordre le plus fréquent est : t, x, y, p.
    On standardise en x, y, t, p.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # esim_py renvoie habituellement un tableau Nx4 dans l ordre t, x, y, p.
    # On reorganise les colonnes pour rester compatible avec le format AER commun.
    events = np.asarray(events)

    if events.size == 0:
        np.savez_compressed(
            out_path,
            x=np.array([], dtype=np.uint16),
            y=np.array([], dtype=np.uint16),
            t=np.array([], dtype=np.float64),
            p=np.array([], dtype=np.uint8),
        )
        return

    if events.ndim != 2 or events.shape[1] < 4:
        raise RuntimeError(f"Format events inattendu : shape={events.shape}")

    t = events[:, 0].astype(np.float64)
    x = events[:, 1].astype(np.uint16)
    y = events[:, 2].astype(np.uint16)
    p = events[:, 3].astype(np.uint8)

    np.savez_compressed(out_path, x=x, y=y, t=t, p=p)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--frames", required=True)
    parser.add_argument("--timestamps", required=True)
    parser.add_argument("--out_npz", required=True)

    parser.add_argument("--contrast_threshold_positive", type=float, default=0.2)
    parser.add_argument("--contrast_threshold_negative", type=float, default=0.2)
    parser.add_argument("--refractory_period_ns", type=float, default=0.0)

    parser.add_argument("--log_eps", type=float, default=1e-3)
    parser.add_argument("--use_log", type=int, default=1)

    args = parser.parse_args()

    import esim_py

    frames_dir = Path(args.frames)
    timestamps_path = Path(args.timestamps)

    if not frames_dir.exists():
        raise FileNotFoundError(f"Dossier frames introuvable : {frames_dir}")

    if not timestamps_path.exists():
        raise FileNotFoundError(f"Fichier timestamps introuvable : {timestamps_path}")

    # La pipeline stocke le refractory period en nanosecondes, alors que esim_py
    # attend une valeur en secondes. La conversion est donc explicite ici.
    refractory_s = float(args.refractory_period_ns) * 1e-9

    simulator = esim_py.EventSimulator(
        float(args.contrast_threshold_positive),
        float(args.contrast_threshold_negative),
        refractory_s,
        float(args.log_eps),
        bool(args.use_log),
    )

    events = simulator.generateFromFolder(
        str(frames_dir.resolve()),
        str(timestamps_path.resolve()),
    )

    save_events_npz(args.out_npz, events)

    print(f"Vid2E CPU / esim_py wrote {len(events)} events to {args.out_npz}")


if __name__ == "__main__":
    main()
