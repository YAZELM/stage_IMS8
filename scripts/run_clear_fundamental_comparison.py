#!/usr/bin/env python
"""Calcule les metriques fondamentales entre VIVID et les simulateurs.

Le script regenere uniquement les CSV et les figures.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

# Ordre et couleurs fixes: les figures restent comparables d une execution a l'autre.
SIM_ORDER = ["vivid", "dvs_voltmeter", "iebcs", "pix2nvs", "v2e", "vid2e"]
SIM_COMPARE_ORDER = [sim for sim in SIM_ORDER if sim != "vivid"]
COLORS = {
    "vivid": "#111111",
    "dvs_voltmeter": "#4C78A8",
    "iebcs": "#F58518",
    "pix2nvs": "#54A24B",
    "v2e": "#B279A2",
    "vid2e": "#E45756",
}

CONDITION_ORDER = ["dark", "global", "local", "varying"]
REGIME_ORDER = ["aggressive", "robust", "unstable"]

# Les noms de sequences portent les conditions experimentales; on les extrait pour analyser par famille.
def sequence_condition(sequence: str):
    name = sequence.lower()
    family = "other"
    for candidate in CONDITION_ORDER:
        if name.startswith(candidate):
            family = candidate
            break

    if "aggressive" in name:
        regime = "aggressive"
    elif "robust" in name:
        regime = "robust"
    elif "unstable" in name:
        regime = "unstable"
    else:
        regime = "other"
    return family, regime

# Lecture des données: on accepte les deux organisations rencontrees pendant le projet.
def choose_npz(path: Path) -> Path | None:
    # Un simulateur peut fournir un dossier par sequence ou directement un fichier .npz.
    if path.is_file() and path.suffix.lower() == ".npz":
        return path

    for name in ("events.npz", "events_from_dat.npz", "events_from_txt.npz"):
        candidate = path / name
        if candidate.exists():
            return candidate

    files = sorted(path.glob("*.npz"))
    return files[0] if files else None


def resolution(simulator: str, args) -> tuple[int, int]:
    if simulator == "vivid":
        return args.vivid_width, args.vivid_height
    return args.width, args.height


def relative_source_path(path: Path, root: Path) -> str:

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def monotonic_ratio_full(t_us: np.ndarray, chunk_size: int = 1_000_000) -> float:
    # Verification complete mais par morceaux: on ne cree pas un enorme np.diff
    # pour les sequences contenant beaucoup d'evenements.
    if t_us.size <= 1:
        return 1.0

    total = 0
    ok = 0
    previous = t_us[0]
    start = 1
    while start < t_us.size:
        end = min(start + chunk_size, t_us.size)
        chunk = t_us[start:end]
        if chunk.size == 0:
            break

        ok += int(chunk[0] >= previous)
        if chunk.size > 1:
            ok += int(np.count_nonzero(np.diff(chunk) >= 0))
        total += int(chunk.size)
        previous = chunk[-1]
        start = end

    return ok / total if total else 1.0


def load_npz(path: Path):
    # La comparaison attend uniquement le format AER defini par le projet:
    # x, y, t, p avec t exprime en secondes. Les conversions amont doivent donc
    # deja avoir normalise les unites et l ordre des colonnes.
    data = np.load(path, allow_pickle=False)
    keys = set(data.files)

    if not {"x", "y", "t", "p"}.issubset(keys):
        raise ValueError(f"{path} doit contenir le format AER strict: x,y,t,p avec t en secondes")

    t_s = data["t"].astype(np.float64)
    t_us = np.round(t_s * 1_000_000).astype(np.int64)
    x = data["x"]
    y = data["y"]
    p = data["p"]

    x = x.astype(np.int64)
    y = y.astype(np.int64)
    p = p.astype(np.int64)

    if p.size:
        vals = set(np.unique(p).tolist())
        if vals.issubset({0, 1}):
            p = np.where(p > 0, 1, -1).astype(np.int8)
        elif vals.issubset({-1, 1}):
            p = p.astype(np.int8)
        elif vals.issubset({1, 255}):
            p = np.where(p == 1, 1, -1).astype(np.int8)
        else:
            p = np.where(p > 0, 1, -1).astype(np.int8)

    return t_us, x, y, p

# Metrique temporelle par pixel: on regarde la dynamique locale plutot qu un delai global trop grossier.
def per_pixel_delay_us(t_us, pixel_id, total_pixels):
    # On garde une case par pixel, meme si certains pixels ne produisent aucun evenement.
    # Le delai n est defini que pour les pixels avec au moins deux evenements.
    if t_us.size == 0:
        return np.nan, 0, 0.0
    counts = np.bincount(pixel_id, minlength=total_pixels)
    valid = counts > 1
    if not np.any(valid):
        return np.nan, 0, 0.0

    t_min = np.full(total_pixels, np.iinfo(np.int64).max, dtype=np.int64)
    t_max = np.zeros(total_pixels, dtype=np.int64)
    np.minimum.at(t_min, pixel_id, t_us)
    np.maximum.at(t_max, pixel_id, t_us)

    delay = (t_max[valid] - t_min[valid]) / (counts[valid] - 1)
    delay = delay[delay > 0]
    pixels_with_delay = int(valid.sum())
    return (
        float(np.mean(delay)) if delay.size else np.nan,
        pixels_with_delay,
        pixels_with_delay / total_pixels if total_pixels else np.nan,
    )


def temporal_windows(simulator, sequence, t_us, window_s):
    # Cette courbe permet de comparer les pics temporels, pas seulement la moyenne globale.
    if t_us.size == 0:
        return []
    t_s = (t_us - t_us.min()) / 1_000_000.0
    duration_s = max(float(t_s.max()), window_s)
    n_bins = max(1, int(np.ceil(duration_s / window_s)))
    counts, edges = np.histogram(t_s, bins=n_bins, range=(0, n_bins * window_s))
    return [
        {
            "simulator": simulator,
            "sequence": sequence,
            "window_index": i,
            "window_start_s": float(edges[i]),
            "events_per_second_window": float(count / window_s),
        }
        for i, count in enumerate(counts)
    ]

# Calcul par sequence: toutes les metriques sont derivees du meme fichier charge en memoire.
def compute_one(simulator: str, sequence: str, path: Path, args):
    width, height = resolution(simulator, args)
    total_pixels = width * height
    t_us, x, y, p = load_npz(path)
    family, regime = sequence_condition(sequence)

    n_events = int(t_us.size)
    duration_s = np.nan
    if n_events:
        duration_s = max((int(t_us.max()) - int(t_us.min())) / 1_000_000.0, 1e-12)

    pixel_id = y.astype(np.int64) * width + x.astype(np.int64)
    active_pixels = int(np.unique(pixel_id).size) if n_events else 0
    n_on = int(np.sum(p > 0)) if n_events else 0
    delay_us, pixels_with_delay, pixels_with_delay_fraction = per_pixel_delay_us(
        t_us, pixel_id, total_pixels
    )

    metrics = {
        "simulator": simulator,
        "sequence": sequence,
        "condition": family,
        "regime": regime,
        "file": str(path),
        "width": width,
        "height": height,
        "duration_s": duration_s,
        "n_events": n_events,
        "events_per_second": n_events / duration_s if n_events else np.nan,
        "events_per_pixel": n_events / total_pixels if total_pixels else np.nan,
        "events_per_second_per_pixel": (
            n_events / duration_s / total_pixels if n_events and total_pixels else np.nan
        ),
        "on_fraction": n_on / n_events if n_events else np.nan,
        "active_pixel_fraction": active_pixels / total_pixels if total_pixels else np.nan,
        "delay_inter_event_per_pixel_us": delay_us,
        "pixels_with_delay": pixels_with_delay,
        "pixels_with_delay_fraction": pixels_with_delay_fraction,
    }

    p_values = set(np.unique(p).tolist()) if n_events else set()
    validation = {
        "simulator": simulator,
        "sequence": sequence,
        "same_length": len(t_us) == len(x) == len(y) == len(p),
        "x_in_bounds": bool(n_events == 0 or (np.min(x) >= 0 and np.max(x) < width)),
        "y_in_bounds": bool(n_events == 0 or (np.min(y) >= 0 and np.max(y) < height)),
        "p_ok": p_values.issubset({-1, 1}),
        "monotonic_ratio": monotonic_ratio_full(t_us),
    }
    windows = temporal_windows(simulator, sequence, t_us, args.window_s)
    return metrics, validation, windows

# Collecte globale: on parcourt tous les simulateurs et toutes les sequences disponibles.
def collect(input_root: Path, args):
    rows = []
    validations = []
    temporal_rows = []

    for sim_dir in sorted(p for p in input_root.iterdir() if p.is_dir()):
        simulator = sim_dir.name

        sequence_items = []
        sequence_items.extend(sorted(p for p in sim_dir.iterdir() if p.is_dir()))
        sequence_items.extend(sorted(p for p in sim_dir.glob("*.npz")))

        for item in sequence_items:
            path = choose_npz(item)
            if path is None:
                continue

            sequence = item.stem if item.is_file() else item.name
            metrics, validation, windows = compute_one(simulator, sequence, path, args)
            metrics["file"] = relative_source_path(path, input_root)
            rows.append(metrics)
            validations.append(validation)
            temporal_rows.extend(windows)
            print(f"ok {simulator}/{sequence}")

    order = {sim: i for i, sim in enumerate(SIM_ORDER)}
    rows.sort(key=lambda r: (order.get(r["simulator"], 99), r["sequence"]))
    validations.sort(key=lambda r: (order.get(r["simulator"], 99), r["sequence"]))
    temporal_rows.sort(
        key=lambda r: (
            order.get(r["simulator"], 99),
            r["sequence"],
            int(r["window_index"]),
        )
    )
    return rows, validations, temporal_rows

# Resume statistique: les moyennes ignorent les NaN pour ne pas bloquer une sequence incomplete.
def mean(values):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.mean(values)) if values.size else np.nan


def ratio(value, ref):
    if not np.isfinite(value) or not np.isfinite(ref) or ref == 0:
        return np.nan
    return float(value / ref)


def rows_by_sequence(rows):
    return {r["sequence"]: r for r in rows}


def paired_ratio_mean(sim_rows, vivid_rows, metric):
    # Comparaison appairee: chaque sequence simulateur est comparee a la meme
    # sequence VIVID, puis les ratios sont moyennes. Cela evite qu'une sequence
    # plus dense domine indirectement toute la synthese globale.
    vivid_by_sequence = rows_by_sequence(vivid_rows)
    values = []
    for row in sim_rows:
        ref = vivid_by_sequence.get(row["sequence"])
        if ref is not None:
            values.append(ratio(row[metric], ref[metric]))
    return mean(values)


def paired_diff_pp_mean(sim_rows, vivid_rows, metric):
    # Meme logique pour les fractions: on moyenne les ecarts par sequence,
    # en points de pourcentage.
    vivid_by_sequence = rows_by_sequence(vivid_rows)
    values = []
    for row in sim_rows:
        ref = vivid_by_sequence.get(row["sequence"])
        if ref is not None and np.isfinite(row[metric]) and np.isfinite(ref[metric]):
            values.append(100 * (row[metric] - ref[metric]))
    return mean(values)


def summarize(rows):
    summary = []
    by_sim = {sim: [r for r in rows if r["simulator"] == sim] for sim in SIM_ORDER}
    vivid = by_sim["vivid"]

    for sim in SIM_ORDER:
        sim_rows = by_sim.get(sim, [])
        if not sim_rows:
            continue
        values = {
            "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
            "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
            "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
            "events_per_second_per_pixel": mean(
                [r["events_per_second_per_pixel"] for r in sim_rows]
            ),
            "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in sim_rows]),
            "delay_inter_event_per_pixel_us": mean(
                [r["delay_inter_event_per_pixel_us"] for r in sim_rows]
            ),
            "pixels_with_delay_fraction": mean(
                [r["pixels_with_delay_fraction"] for r in sim_rows]
            ),
        }
        summary.append(
            {
                "simulator": sim,
                "n_sequences": len(sim_rows),
                **values,
                "events_per_second_vs_vivid": paired_ratio_mean(
                    sim_rows, vivid, "events_per_second"
                ),
                "events_per_pixel_vs_vivid": paired_ratio_mean(
                    sim_rows, vivid, "events_per_pixel"
                ),
                "events_per_second_per_pixel_vs_vivid": paired_ratio_mean(
                    sim_rows, vivid, "events_per_second_per_pixel"
                ),
                "delay_vs_vivid": paired_ratio_mean(
                    sim_rows, vivid, "delay_inter_event_per_pixel_us"
                ),
                "on_fraction_diff_pp_vs_vivid": paired_diff_pp_mean(
                    sim_rows, vivid, "on_fraction"
                ),
                "active_pixel_diff_pp_vs_vivid": paired_diff_pp_mean(
                    sim_rows, vivid, "active_pixel_fraction"
                ),
            }
        )
    return summary


def add_temporal_summary(summary, temporal_rows):
    by_key = {}
    for row in temporal_rows:
        key = (row["simulator"], row["sequence"])
        by_key.setdefault(key, []).append(float(row["events_per_second_window"]))

    for item in summary:
        sim = item["simulator"]
        errors = []
        for (cur_sim, sequence), cur_values in by_key.items():
            if cur_sim != sim:
                continue
            vivid_values = by_key.get(("vivid", sequence))
            if vivid_values is None:
                continue
            n = max(len(cur_values), len(vivid_values))
            if n == 0:
                continue
            # On compare sur une grille commune. Les fenetres absentes sont mises a zero,
            # ce qui penalise aussi une activite qui manque ou deborde dans le temps.
            cur_arr = np.zeros(n, dtype=np.float64)
            vivid_arr = np.zeros(n, dtype=np.float64)
            cur_arr[: len(cur_values)] = cur_values
            vivid_arr[: len(vivid_values)] = vivid_values
            diff = cur_arr - vivid_arr
            errors.append(float(np.sqrt(np.mean(diff**2))))
        item["temporal_window_rmse_vs_vivid"] = mean(errors)
    return summary

# Les moyennes globales peuvent masquer les effets dark/global/local/varying; on resume donc aussi par condition.
def summarize_by_condition(rows):
    grouped = {}
    for row in rows:
        key = (row["condition"], row["simulator"])
        grouped.setdefault(key, []).append(row)

    summaries = []
    for condition in CONDITION_ORDER:
        vivid_rows = grouped.get((condition, "vivid"), [])
        if not vivid_rows:
            continue

        for sim in SIM_ORDER:
            sim_rows = grouped.get((condition, sim), [])
            if not sim_rows:
                continue
            values = {
                "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
                "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
                "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
                "events_per_second_per_pixel": mean(
                    [r["events_per_second_per_pixel"] for r in sim_rows]
                ),
                "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in sim_rows]),
                "delay_inter_event_per_pixel_us": mean(
                    [r["delay_inter_event_per_pixel_us"] for r in sim_rows]
                ),
            }
            summaries.append(
                {
                    "condition": condition,
                    "simulator": sim,
                    "n_sequences": len(sim_rows),
                    **values,
                    "events_per_second_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_second"
                    ),
                    "events_per_pixel_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_pixel"
                    ),
                    "events_per_second_per_pixel_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_second_per_pixel"
                    ),
                    "delay_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "delay_inter_event_per_pixel_us"
                    ),
                    "on_fraction_diff_pp_vs_vivid": paired_diff_pp_mean(
                        sim_rows, vivid_rows, "on_fraction"
                    ),
                    "active_pixel_diff_pp_vs_vivid": paired_diff_pp_mean(
                        sim_rows, vivid_rows, "active_pixel_fraction"
                    ),
                }
            )
    return summaries


def summarize_by_regime(rows):
    grouped = {}
    for row in rows:
        key = (row["regime"], row["simulator"])
        grouped.setdefault(key, []).append(row)

    summaries = []
    for regime in REGIME_ORDER:
        vivid_rows = grouped.get((regime, "vivid"), [])
        if not vivid_rows:
            continue

        for sim in SIM_ORDER:
            sim_rows = grouped.get((regime, sim), [])
            if not sim_rows:
                continue
            values = {
                "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
                "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
                "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
                "events_per_second_per_pixel": mean(
                    [r["events_per_second_per_pixel"] for r in sim_rows]
                ),
                "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in sim_rows]),
                "delay_inter_event_per_pixel_us": mean(
                    [r["delay_inter_event_per_pixel_us"] for r in sim_rows]
                ),
            }
            summaries.append(
                {
                    "regime": regime,
                    "simulator": sim,
                    "n_sequences": len(sim_rows),
                    **values,
                    "events_per_second_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_second"
                    ),
                    "events_per_pixel_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_pixel"
                    ),
                    "events_per_second_per_pixel_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "events_per_second_per_pixel"
                    ),
                    "delay_vs_vivid": paired_ratio_mean(
                        sim_rows, vivid_rows, "delay_inter_event_per_pixel_us"
                    ),
                    "on_fraction_diff_pp_vs_vivid": paired_diff_pp_mean(
                        sim_rows, vivid_rows, "on_fraction"
                    ),
                    "active_pixel_diff_pp_vs_vivid": paired_diff_pp_mean(
                        sim_rows, vivid_rows, "active_pixel_fraction"
                    ),
                }
            )
    return summaries


def best_group_sim(summary_rows, group_key, group_value, key, ratio_key=True):
    candidates = [
        r
        for r in summary_rows
        if r[group_key] == group_value and r["simulator"] != "vivid"
    ]
    if not candidates:
        return None
    if ratio_key:
        # Pour le rapport, on garde une lecture directe:
        # le meilleur ratio est celui qui est le plus proche de 1.
        return min(candidates, key=lambda r: abs(float(r[key]) - 1.0))
    return min(candidates, key=lambda r: abs(float(r[key])))

# Critere de proximite: ratio proche de 1 ou difference proche de 0 selon la nature de la metrique.
METRIC_RULES = [
    ("events/s", "events_per_second_vs_vivid", "ratio"),
    ("events/pixel", "events_per_pixel_vs_vivid", "ratio"),
    ("events/s/pixel", "events_per_second_per_pixel_vs_vivid", "ratio"),
    ("delai", "delay_vs_vivid", "ratio"),
    ("ON ratio", "on_fraction_diff_pp_vs_vivid", "diff"),
    ("pixels utilises", "active_pixel_diff_pp_vs_vivid", "diff"),
]


def metric_distance(value, rule):
    value = float(value)
    if rule == "ratio":
        return abs(value - 1.0)
    return abs(value)


def closest_rows(summary_rows, scope_name, group_key=None, group_order=None):
    if group_key is None:
        groups = [("global", summary_rows)]
    else:
        groups = [
            (group_value, [r for r in summary_rows if r[group_key] == group_value])
            for group_value in group_order
        ]

    rows = []
    for group_value, group_rows in groups:
        candidates = [r for r in group_rows if r["simulator"] != "vivid"]
        if not candidates:
            continue
        for metric_name, key, rule in METRIC_RULES:
            best = min(candidates, key=lambda r: metric_distance(r[key], rule))
            rows.append(
                {
                    "scope": scope_name,
                    "group": group_value,
                    "metric": metric_name,
                    "simulator": best["simulator"],
                    "value": float(best[key]),
                    "distance_to_vivid": metric_distance(best[key], rule),
                    "criterion": (
                        "abs(ratio - 1)" if rule == "ratio" else "abs(diff_pp)"
                    ),
                }
            )
    return rows


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

# Figures: les barplots restent volontairement simples pour faciliter la lecture scientifique.
def grouped_bar(rows, key, title, ylabel, out, log=False, simulators=None):
    simulators = simulators or SIM_ORDER
    scenes = sorted({r["sequence"] for r in rows})
    x = np.arange(len(scenes))
    width = 0.82 / len(simulators)
    fig, ax = plt.subplots(figsize=(11, 5.5))

    for i, sim in enumerate(simulators):
        vals = []
        for scene in scenes:
            row = next((r for r in rows if r["simulator"] == sim and r["sequence"] == scene), None)
            vals.append(np.nan if row is None else float(row[key]))
        ax.bar(
            x + (i - (len(simulators) - 1) / 2) * width,
            vals,
            width,
            label=sim,
            color=COLORS.get(sim, "#777777"),
        )

    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(scenes, rotation=35, ha="right")
    ax.grid(axis="y", alpha=0.25)
    if log:
        ax.set_yscale("log")
    ax.legend(ncol=3)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_temporal_mean(temporal_rows, out):
    grouped = {}
    for row in temporal_rows:
        key = (row["simulator"], int(row["window_index"]))
        grouped.setdefault(key, []).append(float(row["events_per_second_window"]))

    fig, ax = plt.subplots(figsize=(11, 5.2))
    for sim in SIM_ORDER:
        indices = sorted(i for s, i in grouped if s == sim)
        if not indices:
            continue
        y = [mean(grouped[(sim, i)]) for i in indices]
        x = indices
        ax.plot(x, y, label=sim, color=COLORS.get(sim, "#777777"), linewidth=1.8)

    ax.set_title("Events/s par fenetre temporelle")
    ax.set_xlabel("fenetre temporelle")
    ax.set_ylabel("events/s moyen")
    ax.set_yscale("log")
    ax.grid(alpha=0.25)
    ax.legend(ncol=3)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)




def temporal_rmse_by_sequence(temporal_rows):
    # Meme logique que la RMSE globale, mais sans moyenner les sequences.
    # Cela permet de voir si une bonne moyenne cache une sequence mal reproduite.
    by_key = {}
    for row in temporal_rows:
        key = (row["simulator"], row["sequence"])
        by_key.setdefault(key, []).append(float(row["events_per_second_window"]))

    rows = []
    sequences = sorted(sequence for sim, sequence in by_key if sim == "vivid")
    for sequence in sequences:
        vivid_values = by_key.get(("vivid", sequence))
        if vivid_values is None:
            continue
        for sim in SIM_COMPARE_ORDER:
            cur_values = by_key.get((sim, sequence))
            if cur_values is None:
                continue
            n = max(len(cur_values), len(vivid_values))
            if n == 0:
                continue
            cur_arr = np.zeros(n, dtype=np.float64)
            vivid_arr = np.zeros(n, dtype=np.float64)
            cur_arr[: len(cur_values)] = cur_values
            vivid_arr[: len(vivid_values)] = vivid_values
            rmse = float(np.sqrt(np.mean((cur_arr - vivid_arr) ** 2)))
            rows.append(
                {
                    "simulator": sim,
                    "sequence": sequence,
                    "temporal_window_rmse_vs_vivid": rmse,
                    "n_windows_simulator": len(cur_values),
                    "n_windows_vivid": len(vivid_values),
                    "n_windows_compared": n,
                }
            )
    return rows

def make_figures(rows, temporal_rows, temporal_rmse_rows, out_dir):
    fig_dir = out_dir / "figures"
    grouped_bar(
        rows,
        "events_per_second",
        "Nombre d'evenements par seconde",
        "events/s",
        fig_dir / "01_events_per_second.png",
        log=True,
    )
    grouped_bar(
        rows,
        "events_per_pixel",
        "Nombre d'evenements par pixel",
        "events/pixel",
        fig_dir / "02_events_per_pixel.png",
        log=True,
    )
    grouped_bar(
        rows,
        "events_per_second_per_pixel",
        "Nombre d'evenements par seconde par pixel",
        "events/s/pixel",
        fig_dir / "07_events_per_second_per_pixel.png",
        log=True,
    )
    grouped_bar(
        rows,
        "on_fraction",
        "Ratio d'evenements ON",
        "n_ON / n_events",
        fig_dir / "03_on_fraction.png",
    )
    grouped_bar(
        rows,
        "active_pixel_fraction",
        "Pixels utilises sur pixels totaux",
        "pixels actifs / pixels totaux",
        fig_dir / "04_active_pixel_fraction.png",
    )
    grouped_bar(
        rows,
        "delay_inter_event_per_pixel_us",
        "Delai inter-event moyen par pixel",
        "microsecondes",
        fig_dir / "05_delay_inter_event_per_pixel.png",
        log=True,
    )
    plot_temporal_mean(
        temporal_rows,
        fig_dir / "06_events_per_second_by_temporal_window.png",
    )
    grouped_bar(
        temporal_rmse_rows,
        "temporal_window_rmse_vs_vivid",
        "RMSE events/s par fenetre et par sequence",
        "RMSE events/s",
        fig_dir / "08_temporal_rmse_by_sequence.png",
        log=True,
        simulators=SIM_COMPARE_ORDER,
    )


def fmt(value, digits=3):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(value):
        return "nan"
    if abs(value) >= 1000:
        return f"{value:.2e}"
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.{digits}f}"


def percent(value):
    return f"{100 * float(value):.1f}%"


def table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines

# Point entree CLI: on regenere results/ et figures/, puis on copie le script utilise.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_root", type=Path, nargs="?", default=Path("unified_data"))
    parser.add_argument("output_dir", type=Path, nargs="?", default=Path("comparaison_simple"))
    parser.add_argument("--width", type=int, default=346)
    parser.add_argument("--height", type=int, default=260)
    parser.add_argument("--vivid-width", type=int, default=240)
    parser.add_argument("--vivid-height", type=int, default=180)
    parser.add_argument("--window-s", type=float, default=1.0)
    args = parser.parse_args()

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ("figures", "results"):
        path = out_dir / subdir
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)

    (out_dir / "scripts").mkdir(parents=True, exist_ok=True)

    rows, validations, temporal_rows = collect(args.input_root.resolve(), args)
    summary = summarize(rows)
    summary = add_temporal_summary(summary, temporal_rows)
    condition_summary = summarize_by_condition(rows)
    regime_summary = summarize_by_regime(rows)
    temporal_rmse_rows = temporal_rmse_by_sequence(temporal_rows)
    closest_global = closest_rows(summary, "global")
    closest_condition = closest_rows(
        condition_summary, "condition", "condition", CONDITION_ORDER
    )
    closest_regime = closest_rows(regime_summary, "regime", "regime", REGIME_ORDER)

    write_csv(out_dir / "results" / "metrics_by_sequence.csv", rows)
    write_csv(out_dir / "results" / "events_per_second_by_window.csv", temporal_rows)
    write_csv(out_dir / "results" / "temporal_rmse_by_sequence.csv", temporal_rmse_rows)
    write_csv(out_dir / "results" / "summary.csv", summary)
    write_csv(out_dir / "results" / "summary_by_condition.csv", condition_summary)
    write_csv(out_dir / "results" / "summary_by_regime.csv", regime_summary)
    write_csv(out_dir / "results" / "closest_global.csv", closest_global)
    write_csv(out_dir / "results" / "closest_by_condition.csv", closest_condition)
    write_csv(out_dir / "results" / "closest_by_regime.csv", closest_regime)
    write_csv(out_dir / "results" / "validation.csv", validations)
    make_figures(rows, temporal_rows, temporal_rmse_rows, out_dir)

    script_copy = out_dir / "scripts" / Path(__file__).name
    if Path(__file__).resolve() != script_copy.resolve():
        shutil.copy2(Path(__file__), script_copy)

    print(f"wrote figures and csv to {out_dir}")


if __name__ == "__main__":
    main()
