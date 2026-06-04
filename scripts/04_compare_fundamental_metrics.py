#!/usr/bin/env python3
"""
Comparaison fondamentale entre ViViD++ réel et les simulateurs.

Le script lit les événements unifiés en NPZ et calcule :
- le nombre d'événements par seconde ;
- le nombre d'événements par pixel ;
- la fraction d'événements ON ;
- la fraction de pixels actifs ;
- le délai inter-événement moyen par pixel ;
- le nombre d'événements par seconde par fenêtre temporelle.
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


def choose_npz(path: Path) -> Path | None:
    """Retourne le fichier NPZ à utiliser pour une séquence."""
    if path.is_file() and path.suffix == ".npz":
        return path

    for name in ("events.npz", "events_from_dat.npz", "events_from_txt.npz"):
        candidate = path / name
        if candidate.exists():
            return candidate

    files = sorted(path.glob("*.npz"))
    return files[0] if files else None


def résolution(simulator: str, args) -> tuple[int, int]:
    if simulator == "vivid":
        return args.vivid_width, args.vivid_height
    return args.width, args.height


def load_npz(path: Path):
    """Charge un fichier NPZ au format AER.

    Deux formats sont acceptés :
    - t_us, x, y, p avec temps en microsecondes ;
    - x, y, t, p avec temps en secondes.
    """
    data = np.load(path, allow_pickle=False)
    keys = set(data.files)

    if {"t_us", "x", "y", "p"}.issubset(keys):
        t_us = data["t_us"].astype(np.int64)
        x = data["x"]
        y = data["y"]
        p = data["p"]
    elif {"x", "y", "t", "p"}.issubset(keys):
        t_s = data["t"].astype(np.float64)
        t_us = np.round(t_s * 1_000_000).astype(np.int64)
        x = data["x"]
        y = data["y"]
        p = data["p"]
    else:
        raise ValueError(f"{path} doit contenir t_us,x,y,p ou x,y,t,p")

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


def per_pixel_delay_us(t_us, pixel_id, total_pixels):
    # On crée une case pour chaque pixel du capteur.
    # Un delai inter-event existe seulement si le pixel a au moins 2 événements.
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
    # Courbe simple: nombre d'événements par seconde dans chaque fenetre.
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
    width, height = résolution(simulator, args)
    total_pixels = width * height
    t_us, x, y, p = load_npz(path)

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
    """Collecte les fichiers NPZ, quelle que soit la structure utilisée."""
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
        "Nombre d'événements par seconde",
        "events/s",
        fig_dir / "01_events_per_second.png",
        log=True,
    )
    grouped_bar(
        rows,
        "events_per_pixel",
        "Nombre d'événements par pixel",
        "events/pixel",
        fig_dir / "02_events_per_pixel.png",
        log=True,
    )
    grouped_bar(
        rows,
        "on_fraction",
        "Ratio d'événements ON",
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
        "Délai inter-event moyen par pixel",
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


def write_report(out_dir, rows, summary, validations):
    invalid = [
        r
        for r in validations
        if not (r["same_length"] and r["x_in_bounds"] and r["y_in_bounds"] and r["p_ok"])
    ]
    non_mono = [r for r in validations if float(r["monotonic_ratio_sample"]) < 0.99]

    def row(sim):
        return next(r for r in summary if r["simulator"] == sim)

    lines = [
        "# Comparaison fondamentale des simulateurs",
        "",
        "## Ce qui est comparé",
        "",
        "Cette comparaison garde quatre métriques principales :",
        "",
        "- `events/s`: nombre d'événements par seconde.",
        "- `events/pixel`: nombre total d'événements divisé par le nombre total de pixels du capteur.",
        "- `ON ratio`: proportion d'événements ON, calculée par `n_ON / n_events`.",
        "- `pixels utilisés`: proportion de pixels qui ont produit au moins un evenement.",
        "",
        "Deux contrôles temporels sont ajoutés :",
        "",
        "- `délai inter-événement par pixel`: calcule en parcourant tous les pixels du capteur.",
        "- `events/s par fenêtre`: calcule avec des fenêtres temporelles régulières.",
        "",
        "VIVID est la référence de comparaison. Il apparait aussi dans les figures comme une méthode a part entiere.",
        "",
        "## Formules",
        "",
        "- `events/s = n_events / durée`",
        "- `events/pixel = n_events / (largeur * hauteur)`",
        "- `ON ratio = n_ON / n_events`",
        "- `pixels utilisés = pixels_actifs / pixels_totaux`",
        "- `delai_pixel = (t_dernier - t_premier) / (n_events_pixel - 1)` pour les pixels avec au moins deux événements",
        "",
        "La résolution utilisée est `240x180` pour VIVID et `346x260` pour les simulateurs.",
        "Pour le delai, le script crée une case pour chaque pixel du capteur. Les pixels avec moins de deux événements sont comptes, mais ils n'ont pas de délai inter-event defini.",
        "",
        "## Vérification rapide",
        "",
        f"- Fichiers analysés: {len(validations)}.",
        f"- Fichiers invalides: {len(invalid)}.",
        f"- Fichiers avec timestamps non ordonnés sur échantillon: {len(non_mono)}.",
        "",
    ]

    if non_mono:
        lines += [
            "Les timestamps non ordonnés concernent `pix2nvs`. Les quatre métriques restent utilisables, car elles ne dépendent pas de l'ordre des lignes.",
            "",
        ]

    lines += [
        "## Résultats moyens",
        "",
    ]
    lines += table(
        [
            "Source",
            "events/s",
            "events/pixel",
            "ON ratio",
            "pixels utilisés",
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
        "## Interprétation",
        "",
        "- VIVID produit en moyenne environ `1.95e5 events/s` et `109.7 events/pixel`.",
        "- `pix2nvs` est le plus proche de VIVID en nombre d'événements par seconde, mais il utilise moins de pixels et ses timestamps doivent etre contrôles avant une analyse temporelle fine.",
        "- `iebcs` est le plus equilibre sur les quatre métriques: volume modere, ratio ON proche, et presque tous les pixels sont utilises.",
        "- `dvs_voltmeter` active presque tout le capteur, mais produit environ 5 fois plus d'événements par seconde que VIVID et un ratio ON plus eleve.",
        "- `v2e` et `vid2e` produisent beaucoup trop d'événements par rapport a VIVID dans ces donnees.",
        "- Le délai inter-événement par pixel aide a vérifiér si cette sur-production correspond aussi a des événements beaucoup plus rapproches dans le temps.",
        "- La figure `events/s par fenêtre` permet de voir si les pics temporels suivent la meme forme que VIVID ou seulement le meme volume moyen.",
        "",
        "Conclusion: si le critère principal est le volume d'événements, `pix2nvs` est le plus proche. Si on cherche un comportement global plus stable sur les quatre métriques, `iebcs` est le candidat le plus cohérent.",
        "",
        "## Hypothèses",
        "",
        "- `v2e` et `vid2e` peuvent sur-produire car ils utilisent des modèles/interpolations qui rendent les variations temporelles plus denses.",
        "- `dvs_voltmeter` ajoute une modélisation stochastique du capteur, ce qui peut augmenter l'activité et la couverture du capteur.",
        "- `iebcs` semble plus contraint par ses paramètres de capteur: seuil, latence, jitter et période réfractaire.",
        "- `pix2nvs` semble proche en volume, mais son ordre temporel doit etre vérifié plus soigneusement.",
        "",
        "## Figures",
        "",
        "![events/s](figures/01_events_per_second.png)",
        "",
        "![events/pixel](figures/02_events_per_pixel.png)",
        "",
        "![ON ratio](figures/03_on_fraction.png)",
        "",
        "![pixels utilisés](figures/04_active_pixel_fraction.png)",
        "",
        "![délai inter-événement par pixel](figures/05_delay_inter_event_per_pixel.png)",
        "",
        "![events/s par fenêtre](figures/06_events_per_second_by_temporal_window.png)",
        "",
        "## Métriques utiles à ajouter ensuite",
        "",
        "- Hot pixels: utile pour séparer bruit de capteur et activité utile.",
        "- Sensibilité aux seuils ON/OFF: utile car plusieurs simulateurs dépendent fortement du seuil de contraste.",
        "",
        "## Sources utilisées pour interpreter les simulateurs",
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

- 4 métriques principales
- 2 contrôles temporels
- 6 figures
- 4 CSV
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

    write_csv(out_dir / "results" / "metrics_by_sequence.csv", rows)
    write_csv(out_dir / "results" / "events_per_second_by_window.csv", temporal_rows)
    write_csv(out_dir / "results" / "summary.csv", summary)
    write_csv(out_dir / "results" / "validation.csv", validations)
    make_figures(rows, temporal_rows, out_dir)
    write_report(out_dir, rows, summary, validations)
    write_readme(out_dir)
    (out_dir / "requirements.txt").write_text("numpy\nmatplotlib\n", encoding="utf-8")
    shutil.copy2(Path(__file__), out_dir / "scripts" / Path(__file__).name)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
