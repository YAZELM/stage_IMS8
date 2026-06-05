#!/usr/bin/env python3
"""
Comparaison simple entre VIVID et les simulateurs.

Le script lit les fichiers unifies en .npz et calcule seulement:
- events/s
- events/pixel
- fraction ON
- fraction de pixels actifs
- delai inter-event par pixel
- events/s par fenetre temporelle
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


SIM_ORDER = ["vivid", "dvs_voltmeter", "iebcs", "pix2nvs", "v2e", "vid2e"]
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


def sequence_condition(sequence: str):
    name = sequence.lower().replace("aggresive", "aggressive")
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


def choose_npz(folder: Path) -> Path | None:
    # Pour IEBCS, on garde la version decodee depuis le dat si elle existe.
    for name in ("events.npz", "events_from_dat.npz", "events_from_txt.npz"):
        path = folder / name
        if path.exists():
            return path
    files = sorted(folder.glob("*.npz"))
    return files[0] if files else None


def resolution(simulator: str, args) -> tuple[int, int]:
    if simulator == "vivid":
        return args.vivid_width, args.vivid_height
    return args.width, args.height


def load_npz(path: Path):
    data = np.load(path, allow_pickle=False)
    needed = {"t_us", "x", "y", "p"}
    missing = needed - set(data.files)
    if missing:
        raise ValueError(f"{path} manque les champs {sorted(missing)}")
    return data["t_us"], data["x"], data["y"], data["p"]


def per_pixel_delay_us(t_us, pixel_id, total_pixels):
    # On cree une case pour chaque pixel du capteur.
    # Un delai inter-event existe seulement si le pixel a au moins 2 evenements.
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
    # Courbe simple: nombre d'evenements par seconde dans chaque fenetre.
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
        "on_fraction": n_on / n_events if n_events else np.nan,
        "active_pixel_fraction": active_pixels / total_pixels if total_pixels else np.nan,
        "delay_inter_event_per_pixel_us": delay_us,
        "pixels_with_delay": pixels_with_delay,
        "pixels_with_delay_fraction": pixels_with_delay_fraction,
    }

    sample = slice(0, min(n_events, 1_000_000))
    p_values = set(np.unique(p[sample]).tolist()) if n_events else set()
    validation = {
        "simulator": simulator,
        "sequence": sequence,
        "same_length": len(t_us) == len(x) == len(y) == len(p),
        "x_in_bounds": bool(n_events == 0 or (np.min(x) >= 0 and np.max(x) < width)),
        "y_in_bounds": bool(n_events == 0 or (np.min(y) >= 0 and np.max(y) < height)),
        "p_ok": p_values.issubset({-1, 1}),
        "monotonic_ratio_sample": (
            float(np.mean(np.diff(t_us[sample]) >= 0)) if n_events > 1 else 1.0
        ),
    }
    windows = temporal_windows(simulator, sequence, t_us, args.window_s)
    return metrics, validation, windows


def collect(input_root: Path, args):
    rows = []
    validations = []
    temporal_rows = []
    for sim_dir in sorted(p for p in input_root.iterdir() if p.is_dir()):
        simulator = sim_dir.name
        for seq_dir in sorted(p for p in sim_dir.iterdir() if p.is_dir()):
            path = choose_npz(seq_dir)
            if path is None:
                continue
            metrics, validation, windows = compute_one(simulator, seq_dir.name, path, args)
            rows.append(metrics)
            validations.append(validation)
            temporal_rows.extend(windows)
            print(f"ok {simulator}/{seq_dir.name}")

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


def mean(values):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.mean(values)) if values.size else np.nan


def ratio(value, ref):
    if not np.isfinite(value) or not np.isfinite(ref) or ref == 0:
        return np.nan
    return float(value / ref)


def summarize(rows):
    summary = []
    by_sim = {sim: [r for r in rows if r["simulator"] == sim] for sim in SIM_ORDER}
    vivid = by_sim["vivid"]
    vivid_mean = {
        "events_per_second": mean([r["events_per_second"] for r in vivid]),
        "events_per_pixel": mean([r["events_per_pixel"] for r in vivid]),
        "on_fraction": mean([r["on_fraction"] for r in vivid]),
        "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in vivid]),
        "delay_inter_event_per_pixel_us": mean(
            [r["delay_inter_event_per_pixel_us"] for r in vivid]
        ),
        "pixels_with_delay_fraction": mean([r["pixels_with_delay_fraction"] for r in vivid]),
    }

    for sim in SIM_ORDER:
        sim_rows = by_sim.get(sim, [])
        if not sim_rows:
            continue
        values = {
            "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
            "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
            "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
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
                "events_per_second_vs_vivid": ratio(
                    values["events_per_second"], vivid_mean["events_per_second"]
                ),
                "events_per_pixel_vs_vivid": ratio(
                    values["events_per_pixel"], vivid_mean["events_per_pixel"]
                ),
                "delay_vs_vivid": ratio(
                    values["delay_inter_event_per_pixel_us"],
                    vivid_mean["delay_inter_event_per_pixel_us"],
                ),
                "on_fraction_diff_pp_vs_vivid": 100
                * (values["on_fraction"] - vivid_mean["on_fraction"]),
                "active_pixel_diff_pp_vs_vivid": 100
                * (values["active_pixel_fraction"] - vivid_mean["active_pixel_fraction"]),
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
            n = min(len(cur_values), len(vivid_values))
            if n == 0:
                continue
            diff = np.asarray(cur_values[:n]) - np.asarray(vivid_values[:n])
            errors.append(float(np.sqrt(np.mean(diff**2))))
        item["temporal_window_rmse_vs_vivid"] = mean(errors)
    return summary


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
        vivid_mean = {
            "events_per_second": mean([r["events_per_second"] for r in vivid_rows]),
            "events_per_pixel": mean([r["events_per_pixel"] for r in vivid_rows]),
            "on_fraction": mean([r["on_fraction"] for r in vivid_rows]),
            "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in vivid_rows]),
            "delay_inter_event_per_pixel_us": mean(
                [r["delay_inter_event_per_pixel_us"] for r in vivid_rows]
            ),
        }

        for sim in SIM_ORDER:
            sim_rows = grouped.get((condition, sim), [])
            if not sim_rows:
                continue
            values = {
                "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
                "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
                "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
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
                    "events_per_second_vs_vivid": ratio(
                        values["events_per_second"], vivid_mean["events_per_second"]
                    ),
                    "events_per_pixel_vs_vivid": ratio(
                        values["events_per_pixel"], vivid_mean["events_per_pixel"]
                    ),
                    "delay_vs_vivid": ratio(
                        values["delay_inter_event_per_pixel_us"],
                        vivid_mean["delay_inter_event_per_pixel_us"],
                    ),
                    "on_fraction_diff_pp_vs_vivid": 100
                    * (values["on_fraction"] - vivid_mean["on_fraction"]),
                    "active_pixel_diff_pp_vs_vivid": 100
                    * (values["active_pixel_fraction"] - vivid_mean["active_pixel_fraction"]),
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
        vivid_mean = {
            "events_per_second": mean([r["events_per_second"] for r in vivid_rows]),
            "events_per_pixel": mean([r["events_per_pixel"] for r in vivid_rows]),
            "on_fraction": mean([r["on_fraction"] for r in vivid_rows]),
            "active_pixel_fraction": mean([r["active_pixel_fraction"] for r in vivid_rows]),
            "delay_inter_event_per_pixel_us": mean(
                [r["delay_inter_event_per_pixel_us"] for r in vivid_rows]
            ),
        }

        for sim in SIM_ORDER:
            sim_rows = grouped.get((regime, sim), [])
            if not sim_rows:
                continue
            values = {
                "events_per_second": mean([r["events_per_second"] for r in sim_rows]),
                "events_per_pixel": mean([r["events_per_pixel"] for r in sim_rows]),
                "on_fraction": mean([r["on_fraction"] for r in sim_rows]),
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
                    "events_per_second_vs_vivid": ratio(
                        values["events_per_second"], vivid_mean["events_per_second"]
                    ),
                    "events_per_pixel_vs_vivid": ratio(
                        values["events_per_pixel"], vivid_mean["events_per_pixel"]
                    ),
                    "delay_vs_vivid": ratio(
                        values["delay_inter_event_per_pixel_us"],
                        vivid_mean["delay_inter_event_per_pixel_us"],
                    ),
                    "on_fraction_diff_pp_vs_vivid": 100
                    * (values["on_fraction"] - vivid_mean["on_fraction"]),
                    "active_pixel_diff_pp_vs_vivid": 100
                    * (values["active_pixel_fraction"] - vivid_mean["active_pixel_fraction"]),
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


METRIC_RULES = [
    ("events/s", "events_per_second_vs_vivid", "ratio"),
    ("events/pixel", "events_per_pixel_vs_vivid", "ratio"),
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


def grouped_bar(rows, key, title, ylabel, out, log=False):
    scenes = sorted({r["sequence"] for r in rows})
    x = np.arange(len(scenes))
    width = 0.82 / len(SIM_ORDER)
    fig, ax = plt.subplots(figsize=(11, 5.5))

    for i, sim in enumerate(SIM_ORDER):
        vals = []
        for scene in scenes:
            row = next((r for r in rows if r["simulator"] == sim and r["sequence"] == scene), None)
            vals.append(np.nan if row is None else float(row[key]))
        ax.bar(
            x + (i - (len(SIM_ORDER) - 1) / 2) * width,
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


def make_figures(rows, temporal_rows, out_dir):
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


def write_report(
    out_dir,
    rows,
    summary,
    condition_summary,
    regime_summary,
    closest_global,
    closest_condition,
    closest_regime,
    validations,
):
    invalid = [
        r
        for r in validations
        if not (r["same_length"] and r["x_in_bounds"] and r["y_in_bounds"] and r["p_ok"])
    ]
    non_mono = [r for r in validations if float(r["monotonic_ratio_sample"]) < 0.99]

    def summary_row(sim):
        return next(r for r in summary if r["simulator"] == sim)

    vivid = summary_row("vivid")
    pix2nvs = summary_row("pix2nvs")
    iebcs = summary_row("iebcs")
    v2e = summary_row("v2e")
    vid2e = summary_row("vid2e")
    closest_global_by_metric = {r["metric"]: r for r in closest_global}

    lines = [
        "# Comparaison simple des simulateurs",
        "",
        "## Objectif",
        "",
        "Le but est de comparer VIVID aux simulateurs avec peu de metriques, mais de les lire correctement selon les conditions de scene.",
        "VIVID est utilise comme reference et reste visible dans chaque figure.",
        "",
        "Les metriques principales sont `events/s`, `events/pixel`, `ON ratio` et `pixels utilises`.",
        "Deux controles temporels completent la lecture: le delai inter-event par pixel et les `events/s` par fenetre temporelle.",
        "",
        "## Methode courte",
        "",
        "- `events/s = n_events / duree`.",
        "- `events/pixel = n_events / (largeur * hauteur)`.",
        "- `ON ratio = n_ON / n_events`.",
        "- `pixels utilises = pixels_actifs / pixels_totaux`.",
        "- `delai_pixel = (t_dernier - t_premier) / (n_events_pixel - 1)` pour chaque pixel avec au moins deux evenements.",
        "",
        "Le calcul du delai considere bien tous les pixels du capteur. Les pixels avec moins de deux evenements sont comptes, mais ils n'ont pas de delai inter-event defini.",
        "Les resolutions utilisees sont `240x180` pour VIVID et `346x260` pour les simulateurs.",
        "",
        "## Verification rapide",
        "",
        f"- Fichiers analyses: {len(validations)}.",
        f"- Fichiers invalides: {len(invalid)}.",
        f"- Fichiers avec timestamps non ordonnes sur echantillon: {len(non_mono)}.",
        "",
    ]

    if non_mono:
        lines += [
            "Les timestamps non ordonnes concernent `pix2nvs`. Les metriques de comptage restent exploitables, mais toute analyse temporelle fine de `pix2nvs` doit rester prudente.",
            "",
        ]

    lines += [
        "## Vue globale des resultats",
        "",
    ]
    lines += table(
        [
            "Source",
            "events/s",
            "events/pixel",
            "ON ratio",
            "pixels utilises",
            "delai/pixel",
            "pixels avec delai",
            "events/s vs VIVID",
            "events/pixel vs VIVID",
            "delai vs VIVID",
            "RMSE fenetres",
        ],
        [
            [
                r["simulator"],
                fmt(r["events_per_second"]),
                fmt(r["events_per_pixel"]),
                percent(r["on_fraction"]),
                percent(r["active_pixel_fraction"]),
                fmt(r["delay_inter_event_per_pixel_us"]),
                percent(r["pixels_with_delay_fraction"]),
                fmt(r["events_per_second_vs_vivid"]),
                fmt(r["events_per_pixel_vs_vivid"]),
                fmt(r["delay_vs_vivid"]),
                fmt(r["temporal_window_rmse_vs_vivid"]),
            ]
            for r in summary
        ],
    )

    lines += [
        "",
        "## Critere de proximite",
        "",
        "Pour eviter toute ambiguite, le meme critere est applique partout dans le rapport:",
        "",
        "- pour un ratio, le plus proche de VIVID minimise `abs(ratio - 1)`;",
        "- pour une difference en points de pourcentage, le plus proche minimise `abs(diff_pp)`.",
        "",
        "Application globale du critere:",
        "",
    ]
    lines += table(
        ["Metrique", "Plus proche", "Valeur", "Distance", "Critere"],
        [
            [
                r["metric"],
                r["simulator"],
                fmt(r["value"]),
                fmt(r["distance_to_vivid"]),
                r["criterion"],
            ]
            for r in closest_global
        ],
    )

    lines += [
        "",
        "## Volume d'evenements",
        "",
        f"VIVID produit en moyenne `{fmt(vivid['events_per_second'])}` events/s. `pix2nvs` reste le plus proche en volume moyen, meme s'il reste au-dessus de VIVID avec un facteur `{fmt(pix2nvs['events_per_second_vs_vivid'])}`.",
        f"`v2e` et `vid2e` sont nettement plus eleves: environ `{fmt(v2e['events_per_second_vs_vivid'])}`x et `{fmt(vid2e['events_per_second_vs_vivid'])}`x VIVID.",
        "Cela suggere une generation d'evenements plus dense, probablement liee aux seuils, au bruit ou a l'interpolation temporelle.",
        "",
        "![events/s](figures/01_events_per_second.png)",
        "",
        "## Evenements par pixel",
        "",
        "Cette metrique corrige la difference de resolution entre VIVID et les simulateurs.",
        f"Sur la moyenne globale, `pix2nvs` est le plus proche de VIVID avec un facteur `{fmt(pix2nvs['events_per_pixel_vs_vivid'])}`: il est legerement en dessous de VIVID, alors que `iebcs` est au-dessus avec un facteur `{fmt(iebcs['events_per_pixel_vs_vivid'])}`.",
        "`iebcs` reste interessant car il garde une couverture du capteur tres complete, mais il n'est pas le plus proche globalement sur `events/pixel`.",
        "`v2e` et `vid2e` restent largement au-dessus, donc l'ecart de volume ne vient pas seulement du nombre de pixels du capteur.",
        "",
        "![events/pixel](figures/02_events_per_pixel.png)",
        "",
        "## Ratio ON",
        "",
        "VIVID a un ratio ON plus bas que la plupart des simulateurs. Les simulateurs tendent souvent vers une polarite plus proche de 50/50.",
        "Cette difference peut indiquer que les modeles de seuil ON/OFF ou de contraste ne reproduisent pas exactement le desequilibre de VIVID.",
        "",
        "![ON ratio](figures/03_on_fraction.png)",
        "",
        "## Pixels utilises",
        "",
        "La plupart des methodes activent une grande partie du capteur, mais `pix2nvs`, `v2e` et `vid2e` utilisent moins de pixels dans certaines conditions, surtout dans les scenes sombres.",
        "Cette metrique aide a distinguer un simulateur qui produit beaucoup d'evenements partout d'un simulateur qui concentre l'activite sur moins de pixels.",
        "",
        "![pixels utilises](figures/04_active_pixel_fraction.png)",
        "",
        "## Delai inter-event par pixel",
        "",
        "Le delai inter-event complete la lecture du volume: si un simulateur produit beaucoup plus d'evenements, on s'attend souvent a des delais plus courts.",
        "`v2e` et `vid2e` ont effectivement des delais beaucoup plus courts que VIVID, ce qui confirme une dynamique plus dense.",
        "`pix2nvs` est proche de VIVID sur le delai moyen, mais la remarque sur l'ordre temporel reste importante.",
        "",
        "![delai inter-event par pixel](figures/05_delay_inter_event_per_pixel.png)",
        "",
        "## Events/s par fenetre temporelle",
        "",
        "Cette figure montre si les pics d'activite arrivent globalement aux memes moments.",
        "Elle evite de conclure uniquement a partir d'une moyenne: deux simulateurs peuvent avoir un volume moyen proche mais des pics temporels mal places.",
        "",
        "![events/s par fenetre](figures/06_events_per_second_by_temporal_window.png)",
        "",
        "## Analyse par condition",
        "",
        "Les moyennes globales cachent une partie du comportement. Ici, chaque condition est comparee a VIVID dans la meme condition.",
        "",
    ]
    lines += table(
        [
            "Condition",
            "Source",
            "events/s vs VIVID",
            "events/pixel vs VIVID",
            "ON diff pp",
            "pixels diff pp",
            "delai vs VIVID",
        ],
        [
            [
                r["condition"],
                r["simulator"],
                fmt(r["events_per_second_vs_vivid"]),
                fmt(r["events_per_pixel_vs_vivid"]),
                fmt(r["on_fraction_diff_pp_vs_vivid"]),
                fmt(r["active_pixel_diff_pp_vs_vivid"]),
                fmt(r["delay_vs_vivid"]),
            ]
            for r in condition_summary
        ],
    )

    lines += [
        "",
        "Meilleurs simulateurs par condition avec le critere uniforme:",
        "",
    ]
    lines += table(
        ["Condition", "Metrique", "Plus proche", "Valeur", "Distance", "Critere"],
        [
            [
                r["group"],
                r["metric"],
                r["simulator"],
                fmt(r["value"]),
                fmt(r["distance_to_vivid"]),
                r["criterion"],
            ]
            for r in closest_condition
        ],
    )

    lines += [
        "",
        "Lecture synthetique:",
        "",
        "Ici, `plus proche` signifie: ratio le plus proche de `1` pour `events/s`, `events/pixel` et le delai; ecart le plus proche de `0` pour le ratio ON.",
        "",
    ]
    for condition in CONDITION_ORDER:
        best_rate = best_group_sim(
            condition_summary, "condition", condition, "events_per_second_vs_vivid", True
        )
        best_pixel = best_group_sim(
            condition_summary, "condition", condition, "events_per_pixel_vs_vivid", True
        )
        best_on = best_group_sim(
            condition_summary, "condition", condition, "on_fraction_diff_pp_vs_vivid", False
        )
        if best_rate is None:
            continue
        lines += [
            f"- `{condition}`: plus proche en `events/s`: `{best_rate['simulator']}`; plus proche en `events/pixel`: `{best_pixel['simulator']}`; plus proche en ratio ON: `{best_on['simulator']}`.",
        ]

    lines += [
        "",
        "`dark` met davantage en evidence le bruit et les seuils de declenchement. `global` et `local` revelent surtout les ecarts de volume. `varying` teste la robustesse quand l'intensite change au cours du temps.",
        "",
        "## Analyse par regime",
        "",
        "Les regimes `aggressive`, `robust` et `unstable` donnent une deuxieme lecture des memes donnees.",
        "",
    ]
    lines += table(
        [
            "Regime",
            "Source",
            "events/s vs VIVID",
            "events/pixel vs VIVID",
            "ON diff pp",
            "pixels diff pp",
            "delai vs VIVID",
        ],
        [
            [
                r["regime"],
                r["simulator"],
                fmt(r["events_per_second_vs_vivid"]),
                fmt(r["events_per_pixel_vs_vivid"]),
                fmt(r["on_fraction_diff_pp_vs_vivid"]),
                fmt(r["active_pixel_diff_pp_vs_vivid"]),
                fmt(r["delay_vs_vivid"]),
            ]
            for r in regime_summary
        ],
    )

    lines += [
        "",
        "Meilleurs simulateurs par regime avec le critere uniforme:",
        "",
    ]
    lines += table(
        ["Regime", "Metrique", "Plus proche", "Valeur", "Distance", "Critere"],
        [
            [
                r["group"],
                r["metric"],
                r["simulator"],
                fmt(r["value"]),
                fmt(r["distance_to_vivid"]),
                r["criterion"],
            ]
            for r in closest_regime
        ],
    )

    lines += [
        "",
        "Lecture synthetique:",
        "",
        "Le meme critere est utilise: ratio le plus proche de `1`, ou ecart ON le plus proche de `0`.",
        "",
    ]
    for regime in REGIME_ORDER:
        best_rate = best_group_sim(
            regime_summary, "regime", regime, "events_per_second_vs_vivid", True
        )
        best_pixel = best_group_sim(
            regime_summary, "regime", regime, "events_per_pixel_vs_vivid", True
        )
        best_on = best_group_sim(
            regime_summary, "regime", regime, "on_fraction_diff_pp_vs_vivid", False
        )
        if best_rate is None:
            continue
        lines += [
            f"- `{regime}`: plus proche en `events/s`: `{best_rate['simulator']}`; plus proche en `events/pixel`: `{best_pixel['simulator']}`; plus proche en ratio ON: `{best_on['simulator']}`.",
        ]

    lines += [
        "",
        "## Conclusion",
        "",
        f"Globalement, le plus proche de VIVID est `{closest_global_by_metric['events/s']['simulator']}` pour `events/s`, `{closest_global_by_metric['events/pixel']['simulator']}` pour `events/pixel`, `{closest_global_by_metric['delai']['simulator']}` pour le delai, `{closest_global_by_metric['ON ratio']['simulator']}` pour le ratio ON, et `{closest_global_by_metric['pixels utilises']['simulator']}` pour la couverture de pixels.",
        "`pix2nvs` ressort donc tres proche sur plusieurs mesures globales. Cette proximite doit toutefois etre lue avec prudence, car ses timestamps ne sont pas toujours ordonnes et sa couverture de pixels est plus faible.",
        "`iebcs` n'est pas le meilleur sur le volume global, mais il apparait comme un compromis propre: volume modere, ratio ON relativement proche, et couverture quasi complete du capteur.",
        "`dvs_voltmeter` couvre tres bien le capteur, mais son volume et son ratio ON sont plus eloignes de VIVID.",
        "`v2e` et `vid2e` produisent beaucoup plus d'evenements que VIVID et des delais inter-event plus courts, ce qui indique une dynamique plus dense.",
        "",
        "## Limites possibles",
        "",
        "- VIVID est traite comme reference, mais cela ne prouve pas qu'il soit une verite absolue pour toutes les scenes.",
        "- Les simulateurs n'ont pas forcement ete calibres avec les memes seuils, bruit, latence ou modele de capteur.",
        "- `events/pixel` corrige la resolution, mais ne corrige pas tous les effets lies a la geometrie ou au champ de vue.",
        "- Les timestamps non ordonnes de `pix2nvs` limitent les conclusions temporelles fines.",
        "- Les figures temporelles sont moyennees sur les sequences; une analyse plus poussee pourrait regarder chaque sequence separement.",
        "",
        "## Sources utilisees pour interpreter les simulateurs",
        "",
        "- v2e: https://github.com/SensorsINI/v2e",
        "- IEBCS: https://github.com/neuromorphicsystems/IEBCS",
        "- DVS-Voltmeter: https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136670571.pdf",
        "- PIX2NVS: https://discovery.ucl.ac.uk/id/eprint/10056312/",
        "- Vid2E: https://openaccess.thecvf.com/content_CVPR_2020/papers/Gehrig_Video_to_Events_Recycling_Video_Datasets_for_Event_Cameras_CVPR_2020_paper.pdf",
    ]

    (out_dir / "RAPPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_readme(out_dir):
    (out_dir / "README.md").write_text(
        """# Comparaison simple

Ouvrir `RAPPORT.md`.

Ce dossier contient une comparaison volontairement courte:

- 4 metriques principales
- 2 controles temporels
- 6 figures
- 9 CSV
- 1 script reproductible
""",
        encoding="utf-8",
    )


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
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "figures").mkdir(parents=True)
    (out_dir / "results").mkdir(parents=True)
    (out_dir / "scripts").mkdir(parents=True)

    rows, validations, temporal_rows = collect(args.input_root.resolve(), args)
    summary = summarize(rows)
    summary = add_temporal_summary(summary, temporal_rows)
    condition_summary = summarize_by_condition(rows)
    regime_summary = summarize_by_regime(rows)
    closest_global = closest_rows(summary, "global")
    closest_condition = closest_rows(
        condition_summary, "condition", "condition", CONDITION_ORDER
    )
    closest_regime = closest_rows(regime_summary, "regime", "regime", REGIME_ORDER)

    write_csv(out_dir / "results" / "metrics_by_sequence.csv", rows)
    write_csv(out_dir / "results" / "events_per_second_by_window.csv", temporal_rows)
    write_csv(out_dir / "results" / "summary.csv", summary)
    write_csv(out_dir / "results" / "summary_by_condition.csv", condition_summary)
    write_csv(out_dir / "results" / "summary_by_regime.csv", regime_summary)
    write_csv(out_dir / "results" / "closest_global.csv", closest_global)
    write_csv(out_dir / "results" / "closest_by_condition.csv", closest_condition)
    write_csv(out_dir / "results" / "closest_by_regime.csv", closest_regime)
    write_csv(out_dir / "results" / "validation.csv", validations)
    make_figures(rows, temporal_rows, out_dir)
    write_report(
        out_dir,
        rows,
        summary,
        condition_summary,
        regime_summary,
        closest_global,
        closest_condition,
        closest_regime,
        validations,
    )
    write_readme(out_dir)
    (out_dir / "requirements.txt").write_text("numpy\nmatplotlib\n", encoding="utf-8")
    shutil.copy2(Path(__file__), out_dir / "scripts" / Path(__file__).name)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
