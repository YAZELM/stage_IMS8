#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pipeline principal pour préparer ViViD++ et lancer les simulateurs DVS.

Le script suit trois étapes simples : préparer les entrées RGB, lancer les
simulateurs configurés dans le YAML, puis garder une trace des commandes et des
temps d'exécution. Les conversions AER et la comparaison scientifique sont
faites ensuite par les scripts du dossier scripts/.
"""

from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys, time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import numpy as np

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML manquant. Installer avec : pip install pyyaml") from exc

try:
    import cv2
except ImportError:
    cv2 = None

# ---------------------------------------------------------------------------
# Petites structures et fonctions utilitaires générales
# ---------------------------------------------------------------------------

@dataclass
class Sequence:
    name: str
    source: Path
    kind: str
    video: Optional[Path] = None
    frame_dir: Optional[Path] = None

def sanitize_name(s: str) -> str:
    s = str(s).strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
    return s.strip("_") or "sequence"

def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Suivi du temps d'exécution
# ---------------------------------------------------------------------------

def format_duration(seconds: float) -> str:
    """Formate une durée en texte court pour les logs."""
    seconds = max(0.0, float(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours >= 1:
        return f"{int(hours):02d}:{int(minutes):02d}:{sec:06.3f}"
    return f"{int(minutes):02d}:{sec:06.3f}"


def append_timing_record(work: Path, record: Dict[str, Any]) -> None:
    """Ajoute une mesure de temps dans un journal JSONL cumulatif."""
    path = work / "pipeline_timings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def load_timing_records(work: Path, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Relit les mesures de temps, en filtrant si besoin sur le run courant."""
    path = work / "pipeline_timings.jsonl"
    if not path.exists():
        return []

    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run_id is None or rec.get("run_id") == run_id:
                records.append(rec)
    return records


def write_timing_summary(work: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Construit un résumé des temps par phase, simulateur et séquence."""
    records = load_timing_records(work, run_id=run_id)

    total_s = 0.0
    by_phase: Dict[str, float] = {}
    by_simulator: Dict[str, float] = {}
    by_sequence: Dict[str, float] = {}

    for rec in records:
        duration_s = float(rec.get("duration_s") or 0.0)
        total_s += duration_s

        phase = str(rec.get("phase") or "unknown")
        by_phase[phase] = by_phase.get(phase, 0.0) + duration_s

        sequence = str(rec.get("sequence") or "unknown")
        by_sequence[sequence] = by_sequence.get(sequence, 0.0) + duration_s

        simulator = rec.get("simulator")
        if simulator:
            simulator = str(simulator)
            by_simulator[simulator] = by_simulator.get(simulator, 0.0) + duration_s

    def pack_totals(values: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
        return {
            key: {
                "duration_s": round(value, 6),
                "duration": format_duration(value),
            }
            for key, value in sorted(values.items())
        }

    summary = {
        "created_at": datetime.now().isoformat(),
        "run_id": run_id,
        "n_records": len(records),
        "total_duration_s": round(total_s, 6),
        "total_duration": format_duration(total_s),
        "by_phase": pack_totals(by_phase),
        "by_simulator": pack_totals(by_simulator),
        "by_sequence": pack_totals(by_sequence),
        "jsonl_log": str((work / "pipeline_timings.jsonl").resolve()),
        "records": records,
    }
    save_json(work / "pipeline_timings.json", summary)
    return summary


def timed_call(work: Path, run_id: str, phase: str, sequence_name: str,
               func: Any, *args: Any, simulator: Optional[str] = None,
               **kwargs: Any) -> Any:
    """Exécute une étape en enregistrant sa durée et son statut."""
    started_at = datetime.now()
    start_perf = time.perf_counter()
    status = "ok"
    error = None

    try:
        return func(*args, **kwargs)
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        ended_at = datetime.now()
        duration_s = time.perf_counter() - start_perf
        record: Dict[str, Any] = {
            "run_id": run_id,
            "phase": phase,
            "sequence": sequence_name,
            "simulator": simulator,
            "status": status,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_s": round(duration_s, 6),
            "duration": format_duration(duration_s),
        }
        if error is not None:
            record["error"] = error

        append_timing_record(work, record)

        label_parts = [phase]
        if simulator:
            label_parts.append(simulator)
        label_parts.append(sequence_name)
        print(f"[TIMER] {' :: '.join(label_parts)} -> {record['duration']} ({status})")

# ---------------------------------------------------------------------------
# Commandes externes et fichiers partagés
# ---------------------------------------------------------------------------

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, dry_run: bool = False, log_path: Optional[Path] = None) -> None:
    printable = " ".join(map(str, cmd))
    print(f"\n[CMD] {printable}")
    if cwd:
        print(f"[CWD] {cwd}")
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n### {datetime.now().isoformat()}\nCWD={cwd}\n{printable}\n")
    if dry_run:
        return
    proc = subprocess.run([str(x) for x in cmd], cwd=str(cwd) if cwd else None, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(proc.stdout)
    if proc.returncode != 0:
        print(proc.stdout)
        raise RuntimeError(f"Commande échouée ({proc.returncode}) : {printable}")

def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Outil introuvable dans PATH : {name}")

def symlink_or_copy(src: Path, dst: Path, overwrite: bool = True) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        if overwrite:
            dst.unlink()
        else:
            return
    try:
        os.symlink(src.resolve(), dst)
    except OSError:
        shutil.copy2(src, dst)

def list_files(root: Path, exts: Iterable[str]) -> List[Path]:
    exts_l = {e.lower() for e in exts}
    return sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts_l])

# ---------------------------------------------------------------------------
# Lecture et préparation des séquences RGB
# ---------------------------------------------------------------------------

def fps_from_ffprobe(video: Path, fallback: float) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            text=True).strip()
        if "/" in out:
            num, den = out.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(out)
        return fps if fps > 0 else fallback
    except Exception:
        return fallback

def find_timestamp_file_near(path: Path) -> Optional[Path]:
    root = path if path.is_dir() else path.parent
    candidates = []
    for pat in ["*timestamp*.txt", "*timestamps*.txt", "*time*.txt", "*timestamp*.csv", "*timestamps*.csv", "*time*.csv"]:
        candidates.extend(root.rglob(pat))
    candidates = [p for p in candidates if p.is_file() and "prepared" not in str(p)]
    return sorted(candidates, key=lambda p: (len(str(p)), str(p)))[0] if candidates else None

def parse_timestamps_file(path: Optional[Path], unit: str = "s") -> Optional[List[float]]:
    """Analyse un fichier de timestamps avec une unité déclarée explicitement.

    Formats acceptes:
    - timestamp
    - index,timestamp
    - timestamp,filename
    - index,timestamp,filename
    - valeurs séparées par espace, virgule ou point-virgule
    """
    if path is None:
        return None

    unit = unit.lower()
    scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}.get(unit)
    if scale is None:
        raise ValueError(f"Unite de timestamp inconnue: {unit}. Utiliser s, ms, us ou ns.")

    vals: List[float] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                nums = []
                for part in re.split(r"[,\s;]+", line):
                    try:
                        nums.append(float(part))
                    except ValueError:
                        pass
                if not nums:
                    continue
                # Si la ligne ressemble à index,timestamp, on prend la seconde valeur.
                # Sinon, on prend la dernière valeur numérique, utile pour timestamp,filename.
                if len(nums) >= 2 and abs(nums[0] - round(nums[0])) < 1e-9:
                    vals.append(nums[1])
                else:
                    vals.append(nums[-1])
    except Exception:
        return None

    if len(vals) < 2:
        return None

    arr = np.asarray(vals, dtype=np.float64) * scale
    arr = arr - arr[0]
    return [float(x) for x in arr]


def parse_timestamp_records(path: Optional[Path], unit: str = "s") -> List[Dict[str, Any]]:
    """Lit les timestamps et, si possible, le nom de frame associé.

    Les sorties de dataset_pipeline utilisent index,timestamp,frame_name. Quand ce
    nom est disponible, il devient la référence pour associer chaque image au bon timestamp.
    """
    if path is None:
        return []

    unit = unit.lower()
    scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}.get(unit)
    if scale is None:
        raise ValueError(f"Unite de timestamp inconnue: {unit}. Utiliser s, ms, us ou ns.")

    records: List[Dict[str, Any]] = []
    image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in re.split(r"[,;\s]+", line) if p.strip()]
                numeric = []
                for idx, part in enumerate(parts):
                    try:
                        numeric.append((idx, float(part)))
                    except ValueError:
                        pass
                if not numeric:
                    continue

                lower_parts = [p.lower() for p in parts]
                if any(token in lower_parts for token in ("timestamp", "time", "frame_name", "filename")):
                    continue

                if len(numeric) >= 2 and abs(numeric[0][1] - round(numeric[0][1])) < 1e-9:
                    timestamp = numeric[1][1]
                else:
                    timestamp = numeric[-1][1]

                frame_name = None
                for part in parts:
                    candidate = Path(part).name
                    if Path(candidate).suffix.lower() in image_exts:
                        frame_name = candidate
                        break
                records.append({"timestamp_s": timestamp * scale, "frame_name": frame_name})
    except Exception:
        return []

    if len(records) < 2:
        return []

    t0 = records[0]["timestamp_s"]
    for rec in records:
        rec["timestamp_s"] = float(rec["timestamp_s"] - t0)
    return records


def frames_from_timestamp_records(frame_dir: Path, records: List[Dict[str, Any]]) -> Optional[List[Path]]:
    named_records = [r for r in records if r.get("frame_name")]
    if not named_records:
        return None

    files = [p for p in frame_dir.iterdir() if p.is_file()]
    by_name = {p.name: p for p in files}
    ordered = []
    missing = []
    for rec in named_records:
        name = Path(str(rec["frame_name"])).name
        match = by_name.get(name)
        if match is None:
            missing.append(name)
        else:
            ordered.append(match)

    if missing:
        preview = ", ".join(missing[:5])
        raise RuntimeError(f"Timestamps RGB: frames introuvables dans {frame_dir}: {preview}")
    return ordered

def write_timestamps(seq_dir: Path, n: int, fps: float, timestamps_s: Optional[List[float]]) -> None:
    if timestamps_s is None or len(timestamps_s) < n:
        timestamps_s = [i / fps for i in range(n)]
    else:
        timestamps_s = timestamps_s[:n]
    (seq_dir / "timestamps_s.txt").write_text("\n".join(f"{t:.9f}" for t in timestamps_s) + "\n")
    (seq_dir / "timestamps_us.txt").write_text("\n".join(str(int(round(t * 1_000_000))) for t in timestamps_s) + "\n")
    (seq_dir / "fps.txt").write_text(f"{fps:.9f}\n")

def candidate_image_dirs(root: Path, image_exts: List[str]) -> List[Path]:
    exts = {e.lower() for e in image_exts}
    counts = {}
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            counts[p.parent] = counts.get(p.parent, 0) + 1
    return sorted([d for d, n in counts.items() if n >= 2], key=lambda d: (-counts[d], str(d)))

def best_image_dir(root: Path, image_exts: List[str], preferred_names: List[str]) -> Optional[Path]:
    candidates = candidate_image_dirs(root, image_exts)
    if not candidates:
        return None
    for preferred in preferred_names:
        for d in candidates:
            if d.name == preferred:
                return d
    return candidates[0]

def is_extracted_vivid_sequence(seq_dir: Path) -> bool:
    """Détecte le format produit par notre pipeline d'extraction ViViD++."""
    return (
        seq_dir.is_dir()
        and (
            (seq_dir / "frames_rgb").is_dir()
            or (seq_dir / "videos" / "rgb.mp4").is_file()
        )
    )


def discover_extracted_vivid_sequences(root: Path) -> List[Sequence]:
    """Récupère les séquences de Dataset/outputs/<sequence> en gardant leurs noms.

    On privilégie frames_rgb quand il existe, car ce dossier permet d'utiliser
    les vrais timestamps RGB fournis dans timestamps/rgb_timestamps.txt.
    """
    sequences: List[Sequence] = []
    if not root.is_dir():
        return sequences
    for seq_dir in sorted(root.iterdir()):
        if not is_extracted_vivid_sequence(seq_dir):
            continue
        frame_dir = seq_dir / "frames_rgb"
        video = seq_dir / "videos" / "rgb.mp4"
        if frame_dir.is_dir():
            sequences.append(Sequence(sanitize_name(seq_dir.name), seq_dir, "frames", frame_dir=frame_dir))
        elif video.is_file():
            sequences.append(Sequence(sanitize_name(seq_dir.name), seq_dir, "video", video=video))
    return sequences

def discover_sequences(cfg: Dict[str, Any]) -> List[Sequence]:
    root = Path(cfg["paths"]["vivid_output"]).expanduser()
    general = cfg["general"]
    video_exts, image_exts = general["video_exts"], general["image_exts"]
    requested = general.get("sequences") or []
    sequences = []

    if requested:
        for item in requested:
            p = Path(item).expanduser()
            if not p.is_absolute():
                p = root / p
            if p.is_file() and p.suffix.lower() in video_exts:
                sequences.append(Sequence(sanitize_name(p.stem), p, "video", video=p))
            elif p.is_dir():
                vids = [x for x in p.iterdir() if x.is_file() and x.suffix.lower() in video_exts]
                if vids:
                    sequences += [Sequence(sanitize_name(v.stem), v, "video", video=v) for v in sorted(vids)]
                else:
                    fd = best_image_dir(p, image_exts, general.get("preferred_image_dirs", []))
                    if fd:
                        sequences.append(Sequence(sanitize_name(p.name), p, "frames", frame_dir=fd))
        return sequences

    if root.is_file() and root.suffix.lower() in video_exts:
        return [Sequence(sanitize_name(root.stem), root, "video", video=root)]

    extracted = discover_extracted_vivid_sequences(root)
    if extracted:
        return extracted

    videos = list_files(root, video_exts)
    if videos:
        for v in videos:
            name = sanitize_name(str(v.relative_to(root).with_suffix("")))
            sequences.append(Sequence(name, v, "video", video=v))
    else:
        for d in candidate_image_dirs(root, image_exts):
            sequences.append(Sequence(sanitize_name(str(d.relative_to(root))), d, "frames", frame_dir=d))

    max_seq = general.get("max_sequences")
    return sequences[:int(max_seq)] if max_seq else sequences

def extract_frames_from_video(video: Path, out_dir: Path, overwrite: bool, dry_run: bool) -> None:
    ensure_tool("ffmpeg")
    if out_dir.exists() and overwrite and not dry_run:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y" if overwrite else "-n", "-i", str(video), "-vsync", "0", str(out_dir / "frame_%06d.png")]
    run_cmd(cmd, dry_run=dry_run)

def normalize_frame_dir(
    src_dir: Path,
    dst_dir: Path,
    resize: Dict[str, Any],
    overwrite: bool,
    ordered_frames: Optional[List[Path]] = None,
) -> int:
    if cv2 is None:
        raise RuntimeError("opencv-python est nécessaire pour normaliser des images.")
    if dst_dir.exists() and overwrite:
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    if ordered_frames is None:
        imgs = sorted([
            p for p in src_dir.iterdir()
            if p.is_file() and p.suffix.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"]
        ])
    else:
        imgs = ordered_frames

    n = 0
    for img in imgs:
        im = cv2.imread(str(img), cv2.IMREAD_COLOR)
        if im is None:
            raise RuntimeError(f"Frame illisible pendant la préparation: {img}")
        if resize.get("enabled"):
            im = cv2.resize(im, (int(resize["width"]), int(resize["height"])), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dst_dir / f"frame_{n:06d}.png"), im)
        n += 1
    return n

def make_video_from_frames(frame_dir: Path, out_video: Path, fps: float, overwrite: bool, dry_run: bool) -> None:
    ensure_tool("ffmpeg")
    frames = sorted(frame_dir.glob("*.png"))
    concat = out_video.parent / "_frames_concat.txt"
    with open(concat, "w", encoding="utf-8") as f:
        for fr in frames:
            f.write(f"file '{fr.resolve()}'\n")
            f.write(f"duration {1.0 / fps:.9f}\n")
        f.write(f"file '{frames[-1].resolve()}'\n")
    cmd = ["ffmpeg", "-y" if overwrite else "-n", "-f", "concat", "-safe", "0", "-i", str(concat),
           "-r", str(fps), "-pix_fmt", "yuv420p", str(out_video)]
    run_cmd(cmd, dry_run=dry_run)

def prepare_sequence(seq: Sequence, cfg: Dict[str, Any]) -> Path:
    general = cfg["general"]
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    prepared = work / "prepared" / seq.name
    frames_dir = prepared / "frames"
    overwrite = bool(general.get("overwrite", True))
    dry_run = bool(general.get("dry_run", False))
    prepared.mkdir(parents=True, exist_ok=True)

    fps_fallback = float(general.get("fps_fallback", 30.0))
    extract_fps = general.get("extract_fps")
    resize = general["resize"]
    timestamp_unit = str(general.get("timestamp_unit", "s"))
    timestamp_file = find_timestamp_file_near(seq.source)
    timestamp_records = parse_timestamp_records(timestamp_file, unit=timestamp_unit)
    timestamps_s = [r["timestamp_s"] for r in timestamp_records] if timestamp_records else None

    if seq.kind == "video" and seq.video:
        src_fps = fps_from_ffprobe(seq.video, fps_fallback)
        fps = float(extract_fps) if extract_fps else src_fps
        canonical_video = prepared / "video.mp4"
        cmd = ["ffmpeg", "-y" if overwrite else "-n"]
        start_s = float(general.get("start_s") or 0.0)
        stop_s = general.get("stop_s")
        if start_s > 0:
            cmd += ["-ss", str(start_s)]
        cmd += ["-i", str(seq.video)]
        if stop_s is not None:
            cmd += ["-t", str(max(0.0, float(stop_s) - start_s))]
        vf = []
        if extract_fps:
            vf.append(f"fps={fps}")
        if resize.get("enabled"):
            vf.append(f"scale={int(resize['width'])}:{int(resize['height'])}")
        if vf:
            cmd += ["-vf", ",".join(vf)]
        cmd += ["-pix_fmt", "yuv420p", str(canonical_video)]
        run_cmd(cmd, dry_run=dry_run)
        extract_frames_from_video(canonical_video, frames_dir, overwrite, dry_run)
    elif seq.kind == "frames" and seq.frame_dir:
        fps = fps_fallback
        if timestamps_s and len(timestamps_s) >= 2:
            dt = (timestamps_s[-1] - timestamps_s[0]) / max(1, len(timestamps_s) - 1)
            if dt > 0:
                fps = 1.0 / dt
        if not dry_run:
            ordered_frames = frames_from_timestamp_records(seq.frame_dir, timestamp_records)
            if ordered_frames is not None:
                timestamps_s = [r["timestamp_s"] for r in timestamp_records if r.get("frame_name")]
            normalize_frame_dir(seq.frame_dir, frames_dir, resize, overwrite, ordered_frames=ordered_frames)
            make_video_from_frames(frames_dir, prepared / "video.mp4", fps, overwrite, dry_run)
    else:
        raise RuntimeError(f"Séquence invalide : {seq}")

    n_frames = 0 if dry_run else len(list(frames_dir.glob("*.png")))
    if not dry_run and n_frames < 2:
        raise RuntimeError(f"Pas assez de frames préparées pour {seq.name}")
    write_timestamps(prepared, n_frames, fps, timestamps_s)
    manifest = {
        "name": seq.name,
        "source": str(seq.source),
        "kind": seq.kind,
        "prepared_at": datetime.now().isoformat(),
        "video": str((prepared / "video.mp4").resolve()),
        "frames": str(frames_dir.resolve()),
        "n_frames": n_frames,
        "fps": fps,
        "timestamps_s": str((prepared / "timestamps_s.txt").resolve()),
        "timestamps_us": str((prepared / "timestamps_us.txt").resolve()),
        "timestamp_source": str(timestamp_file.resolve()) if timestamp_file else None,
        "timestamp_frame_names_used": bool(seq.kind == "frames" and timestamp_records and any(r.get("frame_name") for r in timestamp_records)),
    }
    save_json(prepared / "manifest.json", manifest)
    print(f"[OK] Préparé : {seq.name} ({n_frames} frames, fps={fps:.3f})")
    return prepared

def prepared_sequences(cfg: Dict[str, Any]) -> List[Path]:
    root = Path(cfg["paths"]["work_dir"]).expanduser() / "prepared"
    return sorted([p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists()]) if root.exists() else []

# ---------------------------------------------------------------------------
# Accès à la configuration des simulateurs
# ---------------------------------------------------------------------------

def python_for(cfg: Dict[str, Any], key: str) -> str:
    pythons = cfg["paths"].get("pythons", {})
    return pythons.get(key) or pythons.get("default") or sys.executable

def repo_path(cfg: Dict[str, Any], key: str) -> Path:
    p = Path(cfg["paths"]["repos"][key]).expanduser()
    if not p.exists():
        raise RuntimeError(f"Dépôt introuvable pour {key}: {p}")
    return p

def load_manifest(prepared: Path) -> Dict[str, Any]:
    return json.loads((prepared / "manifest.json").read_text(encoding="utf-8"))

def common_log(work: Path, sim: str, seq_name: str) -> Path:
    return work / "logs" / sim / f"{seq_name}.log"

def link_frames(src_frames: Path, dst_imgs: Path, overwrite: bool) -> int:
    if dst_imgs.exists() and overwrite:
        shutil.rmtree(dst_imgs)
    dst_imgs.mkdir(parents=True, exist_ok=True)
    frames = sorted(src_frames.glob("*.png"))
    for i, fr in enumerate(frames):
        symlink_or_copy(fr, dst_imgs / f"{i:06d}.png", overwrite=True)
    return len(frames)

# ---------------------------------------------------------------------------
# Lancement des simulateurs
# ---------------------------------------------------------------------------

def run_v2e(cfg: Dict[str, Any], prepared: Path) -> None:
    simcfg = cfg["v2e"]
    if not simcfg.get("enabled", True): return
    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "v2e")
    py = python_for(cfg, "v2e")
    out = work / "simulated_events" / "v2e" / manifest["name"]
    out.mkdir(parents=True, exist_ok=True)
    p = simcfg["params"]
    input_path = prepared / "video.mp4" if simcfg.get("input_mode", "video") == "video" else prepared / "frames"
    cmd = [py, str(repo / "v2e.py"), "-i", str(input_path), "-o", str(out), "--overwrite", "--input_frame_rate", str(manifest["fps"])]
    if p.get("no_preview", True): cmd.append("--no_preview")
    if p.get("skip_video_output", True): cmd.append("--skip_video_output")
    if p.get("hdr", False): cmd.append("--hdr")
    if p.get("dvs_preset"):
        cmd.append(f"--{p['dvs_preset']}")
    else:
        cmd += ["--output_width", str(p.get("output_width", 346)), "--output_height", str(p.get("output_height", 260))]
    cmd += ["--auto_timestamp_resolution", str(bool(p.get("auto_timestamp_resolution", True)))]
    if p.get("timestamp_resolution") is not None: cmd += ["--timestamp_resolution", str(p["timestamp_resolution"])]
    if p.get("disable_slomo", False): cmd.append("--disable_slomo")
    if p.get("slomo_model"): cmd += ["--slomo_model", str(p["slomo_model"])]
    if p.get("dvs_params") is not None:
        cmd += ["--dvs_params", str(p["dvs_params"])]
    else:
        for key, flag in {
            "pos_thres": "--pos_thres", "neg_thres": "--neg_thres", "sigma_thres": "--sigma_thres",
            "cutoff_hz": "--cutoff_hz", "leak_rate_hz": "--leak_rate_hz",
            "shot_noise_rate_hz": "--shot_noise_rate_hz", "leak_jitter_fraction": "--leak_jitter_fraction",
            "noise_rate_cov_decades": "--noise_rate_cov_decades", "refractory_period": "--refractory_period",
            "dvs_emulator_seed": "--dvs_emulator_seed"
        }.items():
            if p.get(key) is not None: cmd += [flag, str(p[key])]
        if p.get("photoreceptor_noise", False): cmd.append("--photoreceptor_noise")
    if p.get("dvs_exposure"): cmd += ["--dvs_exposure"] + [str(x) for x in p["dvs_exposure"]]
    if p.get("dvs_text"): cmd += ["--dvs_text", p["dvs_text"]]
    if p.get("dvs_h5"): cmd += ["--dvs_h5", p["dvs_h5"]]
    if p.get("dvs_aedat2"): cmd += ["--dvs_aedat2", p["dvs_aedat2"]]
    cmd += [str(x) for x in p.get("extra_args", [])]
    save_json(out / "command.json", {"cmd": cmd, "params": p, "manifest": manifest})
    run_cmd(cmd, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "v2e", manifest["name"]))

def run_vid2e(cfg: Dict[str, Any], prepared: Path) -> None:
    """Lance Vid2E via un wrapper local basé sur esim_py.

    Le wrapper n'est pas fourni directement par les simulateurs externes : il doit
    être présent dans adapters/. Cette vérification évite de lancer une commande
    incomplète ou différente de la méthode documentée.
    """
    simcfg = cfg["vid2e"]

    if not simcfg.get("enabled", True):
        return

    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "vid2e")
    py = python_for(cfg, "vid2e")
    p = simcfg["params"]

    overwrite = cfg["general"].get("overwrite", True)
    dry_run = cfg["general"].get("dry_run", False)

    out = work / "simulated_events" / "vid2e" / manifest["name"]
    out.mkdir(parents=True, exist_ok=True)

    input_root = work / "simulator_inputs" / "vid2e_cpu" / manifest["name"]
    frames_dir = input_root / "frames"

    link_frames(
        prepared / "frames",
        frames_dir,
        overwrite=overwrite,
    )

    timestamps_file = input_root / "timestamps.txt"
    shutil.copy2(prepared / "timestamps_s.txt", timestamps_file)

    wrapper = Path(__file__).resolve().parent / "adapters" / "run_vid2e_esim_py_sequence.py"

    if not wrapper.exists():
        raise RuntimeError(f"Wrapper Vid2E CPU introuvable : {wrapper}")

    out_npz = out / "events.npz"

    cmd = [
        py,
        str(wrapper),
        "--frames", str(frames_dir),
        "--timestamps", str(timestamps_file),
        "--out_npz", str(out_npz),
        "--contrast_threshold_negative", str(p.get("contrast_threshold_negative", 0.2)),
        "--contrast_threshold_positive", str(p.get("contrast_threshold_positive", 0.2)),
        "--refractory_period_ns", str(p.get("refractory_period_ns", 0)),
        "--log_eps", str(p.get("log_eps", 1e-3)),
        "--use_log", str(int(p.get("use_log", True))),
    ]

    cmd += [str(x) for x in p.get("extra_generate_args", [])]

    save_json(out / "command.json", {
        "cmd": cmd,
        "params": p,
        "manifest": manifest,
        "mode": "cpu_esim_py",
        "repo": str(repo),
        "input_frames": str(frames_dir),
        "timestamps": str(timestamps_file),
        "output_npz": str(out_npz),
    })

    run_cmd(
        cmd,
        cwd=repo,
        dry_run=dry_run,
        log_path=common_log(work, "vid2e_generate", manifest["name"])
    )


def run_iebcs(cfg: Dict[str, Any], prepared: Path) -> None:
    simcfg = cfg["iebcs"]
    if not simcfg.get("enabled", True): return
    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "iebcs")
    py = python_for(cfg, "iebcs")
    out = work / "simulated_events" / "iebcs" / manifest["name"]
    out.mkdir(parents=True, exist_ok=True)
    params_json = out / "params.json"
    save_json(params_json, simcfg["params"])
    wrapper = Path(__file__).parent / "adapters" / "run_iebcs_sequence.py"
    if not wrapper.exists():
        wrapper = Path(__file__).parent / "run_iebcs_sequence.py"
    cmd = [py, str(wrapper), "--repo", str(repo), "--frames", str(prepared / "frames"),
           "--timestamps_us", str(prepared / "timestamps_us.txt"), "--outdir", str(out), "--params_json", str(params_json)]
    save_json(out / "command.json", {"cmd": cmd, "params": simcfg["params"], "manifest": manifest})
    run_cmd(cmd, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "iebcs", manifest["name"]))

def run_dvs_voltmeter(cfg: Dict[str, Any], prepared: Path) -> None:
    simcfg = cfg["dvs_voltmeter"]
    if not simcfg.get("enabled", True): return
    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "dvs_voltmeter")
    py = python_for(cfg, "dvs_voltmeter")
    p = simcfg["params"]
    input_root = work / "simulator_inputs" / "dvs_voltmeter_interp" / manifest["name"]
    seq_in = input_root / manifest["name"]
    out = work / "simulated_events" / "dvs_voltmeter" / manifest["name"]
    link_frames(prepared / "frames", seq_in, overwrite=cfg["general"].get("overwrite", True))
    ts_us = [line.strip() for line in (prepared / "timestamps_us.txt").read_text().splitlines() if line.strip()]
    frames = sorted(seq_in.glob("*.png"))
    with open(seq_in / "info.txt", "w", encoding="utf-8") as f:
        for fr, ts in zip(frames, ts_us):
            f.write(f"{fr.resolve()} {int(float(ts))}\n")
    cmd = [py, str(repo / "main.py"), "--camera_type", str(p.get("camera_type", "DVS346")),
           "--input_dir", str(input_root), "--output_dir", str(out)]
    if p.get("model_para"): cmd += ["--model_para"] + [str(x) for x in p["model_para"]]
    cmd += [str(x) for x in p.get("extra_args", [])]
    save_json(out / "command.json", {"cmd": cmd, "params": p, "manifest": manifest})
    run_cmd(cmd, cwd=repo, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "dvs_voltmeter", manifest["name"]))


def run_pix2nvs(cfg: Dict[str, Any], prepared: Path) -> None:
    """
    Lance PIX2NVS en reproduisant l'organisation qui fonctionne manuellement.

    PIX2NVS doit être lancé depuis son propre dossier Linux_user :
    - l'exécutable est dans ce dossier ;
    - ffmpeg et ffprobe sont dans ce dossier ;
    - la vidéo d'entrée doit être copiée dans input/ ;
    - les sorties sont générées dans events/ ou Events/.
    """
    simcfg = cfg["pix2nvs"]

    if not simcfg.get("enabled", True):
        return

    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "pix2nvs")
    p = simcfg["params"]

    dry_run = cfg["general"].get("dry_run", False)
    overwrite = cfg["general"].get("overwrite", True)

    out = work / "simulated_events" / "pix2nvs" / manifest["name"]
    out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------
    # 1. Trouver l'exécutable PIX2NVS utilisé dans l'installation locale
    # ------------------------------------------------------------
    binary_candidates = [
        repo / "PIX2NVS",
        repo / "pix2nvs",
        repo / "Pix2NVS",
    ]

    binary = None

    for candidate in binary_candidates:
        if candidate.exists() and candidate.is_file():
            binary = candidate
            break

    if binary is None:
        raise RuntimeError(
            f"PIX2NVS: aucun exécutable trouvé dans {repo}. "
            f"Attendu : PIX2NVS, pix2nvs ou Pix2NVS."
        )

    try:
        binary.chmod(binary.stat().st_mode | 0o111)
    except PermissionError:
        pass

    # ------------------------------------------------------------
    # 2. Vérifier que ffmpeg et ffprobe sont disponibles dans le même dossier
    # ------------------------------------------------------------
    for tool in ["ffmpeg", "ffprobe"]:
        tool_path = repo / tool

        if not tool_path.exists():
            raise RuntimeError(
                f"PIX2NVS: {tool} absent dans {repo}. "
                f"Tu as dit que ça marche quand ffmpeg/ffprobe sont dans ce dossier : "
                f"il faut donc les laisser ici."
            )

        try:
            tool_path.chmod(tool_path.stat().st_mode | 0o111)
        except PermissionError:
            pass

    # ------------------------------------------------------------
    # 3. Nettoyer les anciennes entrées/sorties pour éviter de mélanger deux runs
    # ------------------------------------------------------------
    input_dir = repo / "input"

    possible_output_dirs = [
        repo / "events",
        repo / "Events",
        repo / "EVENTS",
        repo / "frames",
        repo / "Frames",
        repo / "FRAMES",
    ]

    if overwrite:
        for d in possible_output_dirs:
            if d.exists():
                shutil.rmtree(d)

        if input_dir.exists():
            shutil.rmtree(input_dir)

    input_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------
    # 4. Placer la vidéo préparée dans input/, comme attendu par PIX2NVS
    # ------------------------------------------------------------
    input_video = input_dir / f"{manifest['name']}.mp4"

    symlink_or_copy(
        prepared / "video.mp4",
        input_video,
        overwrite=True
    )

    # 5. Construire la commande avec les paramètres déclarés dans le YAML.
    cmd = [
        str(binary),
        "-r", str(p.get("reference", 3)),
        "-a", str(p.get("adaptive", 0)),
        "-b", str(p.get("blocksize", 4)),
    ]

    if p.get("maxevents") is not None:
        cmd += ["-m", str(p["maxevents"])]

    cmd += [str(x) for x in p.get("extra_args", [])]

    save_json(out / "command.json", {
        "cmd": cmd,
        "params": p,
        "manifest": manifest,
        "pix2nvs_repo": str(repo),
        "binary": str(binary),
        "input_video": str(input_video),
        "mode": "manual_layout_reproduction",
    })

    # 6. Lancer PIX2NVS depuis son propre dossier de travail.
    run_cmd(
        cmd,
        cwd=repo,
        dry_run=dry_run,
        log_path=common_log(work, "pix2nvs", manifest["name"])
    )

    # 7. Archiver les sorties générées dans runs/simulated_events/pix2nvs/<sequence>.
    copied = False

    for dname in ["events", "Events", "EVENTS"]:
        events_dir = repo / dname

        if events_dir.exists() and not dry_run:
            archived = out / dname

            if archived.exists():
                shutil.rmtree(archived)

            shutil.copytree(events_dir, archived)
            print(f"[PIX2NVS] {dname}/ archivé dans : {archived}")
            copied = True

    for dname in ["frames", "Frames", "FRAMES"]:
        frames_dir = repo / dname

        if frames_dir.exists() and not dry_run:
            archived = out / dname

            if archived.exists():
                shutil.rmtree(archived)

            shutil.copytree(frames_dir, archived)
            print(f"[PIX2NVS] {dname}/ archivé dans : {archived}")

    if not copied:
        raise RuntimeError(
            f"PIX2NVS terminé, mais aucun dossier events/ ou Events/ trouvé dans {repo}."
        )


# ---------------------------------------------------------------------------
# Résumé final et interface CLI
# ---------------------------------------------------------------------------

def write_summary(cfg: Dict[str, Any]) -> None:
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    run_id = cfg.get("_run_id")
    summary = {"created_at": datetime.now().isoformat(), "run_id": run_id, "prepared": [], "outputs": {}}
    for p in prepared_sequences(cfg):
        summary["prepared"].append(load_manifest(p))
    for sim in ["v2e", "vid2e", "iebcs", "dvs_voltmeter", "pix2nvs"]:
        out = work / "simulated_events" / sim
        if out.exists():
            summary["outputs"][sim] = [str(x) for x in sorted(out.iterdir()) if x.is_dir()]
    summary["timings"] = write_timing_summary(work, run_id=run_id)
    save_json(work / "pipeline_summary.json", summary)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", default=None, choices=["all", "v2e", "vid2e", "iebcs", "dvs_voltmeter", "pix2nvs"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_yaml(Path(args.config))
    cfg["_run_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.dry_run:
        cfg["general"]["dry_run"] = True
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    save_json(work / "pipeline_config_used.json", cfg)

    try:
        if args.prepare:
            seqs = discover_sequences(cfg)
            if not seqs:
                raise SystemExit("Aucune séquence RGB/vidéo détectée. Vérifie paths.vivid_output.")
            print(f"[INFO] {len(seqs)} séquence(s) détectée(s).")
            for seq in seqs:
                timed_call(
                    work, cfg["_run_id"], "prepare_sequence", seq.name,
                    prepare_sequence, seq, cfg
                )

        if args.run:
            preps = prepared_sequences(cfg)
            if not preps:
                raise SystemExit("Aucune séquence préparée. Lance d'abord --prepare.")
            runners = {"v2e": run_v2e, "vid2e": run_vid2e, "iebcs": run_iebcs,
                       "dvs_voltmeter": run_dvs_voltmeter, "pix2nvs": run_pix2nvs}
            selected = list(runners.keys()) if args.run == "all" else [args.run]
            for prepared in preps:
                for sim in selected:
                    print(f"\n===== {sim} :: {prepared.name} =====")
                    timed_call(
                        work, cfg["_run_id"], "event_generation", prepared.name,
                        runners[sim], cfg, prepared, simulator=sim
                    )
    finally:
        write_summary(cfg)
        print(f"\n[INFO] Résumé : {work / 'pipeline_summary.json'}")
        print(f"[INFO] Chronométrage : {work / 'pipeline_timings.json'}")

if __name__ == "__main__":
    main()