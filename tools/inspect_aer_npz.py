#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_aer_npz.py

Inspecte un ou plusieurs fichiers AER NPZ.
"""
from __future__ import annotations

# Affiche un résumé rapide d’un fichier NPZ au format AER.
import argparse
from pathlib import Path
import numpy as np

def inspect(path: Path):
    d = np.load(path, allow_pickle=False)
    print("\n=", path)
    print("keys:", list(d.files))
    if {"x", "y", "t", "p"}.issubset(set(d.files)):
        x, y, t, p = d["x"], d["y"], d["t"], d["p"]
        print("N:", len(t))
        if len(t):
            print("x:", int(np.min(x)), int(np.max(x)))
            print("y:", int(np.min(y)), int(np.max(y)))
            print("t:", float(np.min(t)), float(np.max(t)), "duration=", float(np.max(t)-np.min(t)))
            print("p unique:", np.unique(p))
            print("ON ratio:", float(np.mean(p == 1)))
            print("first rows:")
            for i in range(min(10, len(t))):
                print(int(x[i]), int(y[i]), float(t[i]), int(p[i]))
    else:
        print("Format non standard : attendu x,y,t,p")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    for pat in args.paths:
        matches = sorted(Path().glob(str(pat))) if any(c in str(pat) for c in "*?") else [pat]
        for p in matches:
            inspect(p)

if __name__ == "__main__":
    main()
