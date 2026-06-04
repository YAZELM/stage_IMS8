#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Préparation des séquences et lancement des simulateurs DVS."""

from __future__ import annotations
import argparse, json, os, re, shutil, subprocess, sys
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

def parse_timestamps_file(path: Optional[Path]) -> Optional[List[float]]:
    """Parse timestamps robustly and return relative seconds.

    Supported formats:
    - timestamp
    - index,timestamp
    - timestamp,filename
    - index,timestamp,filename
    - whitespace/semicolon/comma separated values

    Unit inference is based on the median positive delta, not on absolute value.
    This avoids corrupting epoch timestamps expressed in seconds.
    """
    if path is None:
        return None

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
                                                                                
                                                                                          
                if len(nums) >= 2 and abs(nums[0] - round(nums[0])) < 1e-9:
                    vals.append(nums[1])
                else:
                    vals.append(nums[-1])
    except Exception:
        return None

    if len(vals) < 2:
        return None

    arr = np.asarray(vals, dtype=np.float64)
    diffs = np.diff(arr)
    diffs = diffs[diffs > 0]
    if diffs.size == 0:
        return None

    med_dt = float(np.median(diffs))

                              
                                  
                                
                                      
                                            
    if med_dt > 1e6:
        arr = arr / 1e9
    elif med_dt > 1e3:
        arr = arr / 1e6
    elif med_dt > 10:
        arr = arr / 1e3
                                                                      

    arr = arr - arr[0]
    return [float(x) for x in arr]

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
    """Detect the output format used by our ViViD++ extraction pipeline."""
    return (
        seq_dir.is_dir()
        and (
            (seq_dir / "frames_rgb").is_dir()
            or (seq_dir / "videos" / "rgb.mp4").is_file()
        )
    )


def discover_extracted_vivid_sequences(root: Path) -> List[Sequence]:
    """Return sequences from Dataset/outputs/<sequence> preserving sequence names.

    We prefer frames_rgb when available because it allows using the real RGB
    timestamps from timestamps/rgb_timestamps.txt.
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

def normalize_frame_dir(src_dir: Path, dst_dir: Path, resize: Dict[str, Any], overwrite: bool) -> int:
    if cv2 is None:
        raise RuntimeError("opencv-python est nécessaire pour normaliser des images.")
    if dst_dir.exists() and overwrite:
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    imgs = sorted([p for p in src_dir.iterdir() if p.is_file() and p.suffix.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"]])
    n = 0
    for img in imgs:
        im = cv2.imread(str(img), cv2.IMREAD_COLOR)
        if im is None:
            continue
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
    timestamps_s = parse_timestamps_file(find_timestamp_file_near(seq.source))

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
            normalize_frame_dir(seq.frame_dir, frames_dir, resize, overwrite)
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
    }
    save_json(prepared / "manifest.json", manifest)
    print(f"[OK] Préparé : {seq.name} ({n_frames} frames, fps={fps:.3f})")
    return prepared

def prepared_sequences(cfg: Dict[str, Any]) -> List[Path]:
    root = Path(cfg["paths"]["work_dir"]).expanduser() / "prepared"
    return sorted([p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists()]) if root.exists() else []

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
    simcfg = cfg["vid2e"]
    if not simcfg.get("enabled", True): return
    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "vid2e")
    py = python_for(cfg, "vid2e")
    p = simcfg["params"]
    original_root = work / "simulator_inputs" / "vid2e_original" / manifest["name"]
    original_seq = original_root / manifest["name"]
    upsampled_root = work / "simulator_inputs" / "vid2e_upsampled" / manifest["name"]
    out = work / "simulated_events" / "vid2e" / manifest["name"]
    overwrite = cfg["general"].get("overwrite", True)
    link_frames(prepared / "frames", original_seq / "imgs", overwrite=overwrite)
    (original_seq / "fps.txt").write_text(f"{manifest['fps']:.9f}\n")
    if p.get("use_upsampling", True):
        cmd_up = [py, str(repo / "upsampling" / "upsample.py"), "--input_dir", str(original_root),
                  "--output_dir", str(upsampled_root)] + [str(x) for x in p.get("extra_upsample_args", [])]
        save_json(out / "upsample_command.json", {"cmd": cmd_up, "params": p, "manifest": manifest})
        run_cmd(cmd_up, cwd=repo, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "vid2e_upsample", manifest["name"]))
        generate_input = upsampled_root
    else:
        generate_input = upsampled_root
        seq_dst = generate_input / manifest["name"]
        link_frames(prepared / "frames", seq_dst / "imgs", overwrite=overwrite)
        shutil.copy2(prepared / "timestamps_s.txt", seq_dst / "timestamps.txt")
    cmd_gen = [py, str(repo / "esim_torch" / "scripts" / "generate_events.py"),
               "--input_dir", str(generate_input), "--output_dir", str(out),
               "--contrast_threshold_negative", str(p.get("contrast_threshold_negative", 0.2)),
               "--contrast_threshold_positive", str(p.get("contrast_threshold_positive", 0.2)),
               "--refractory_period_ns", str(p.get("refractory_period_ns", 0))] + [str(x) for x in p.get("extra_generate_args", [])]
    save_json(out / "generate_command.json", {"cmd": cmd_gen, "params": p, "manifest": manifest})
    run_cmd(cmd_gen, cwd=repo, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "vid2e_generate", manifest["name"]))

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
    simcfg = cfg["pix2nvs"]
    if not simcfg.get("enabled", True): return
    manifest = load_manifest(prepared)
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    repo = repo_path(cfg, "pix2nvs")
    p = simcfg["params"]
    input_dir = repo / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    symlink_or_copy(prepared / "video.mp4", input_dir / f"{manifest['name']}.mp4", overwrite=True)
    binary = repo / "pix2nvs"
    if not binary.exists():
        if cfg["general"].get("dry_run", False):
            print("[DRY] g++ -o pix2nvs src/*.cpp")
        else:
            proc = subprocess.run("g++ -o pix2nvs src/*.cpp", cwd=str(repo), shell=True, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if proc.returncode != 0:
                raise RuntimeError(f"Compilation PIX2NVS échouée : {proc.stdout}")
    out = work / "simulated_events" / "pix2nvs" / manifest["name"]
    out.mkdir(parents=True, exist_ok=True)
    cmd = [str(binary), "-r", str(p.get("reference", 3)), "-a", str(p.get("adaptive", 0)), "-b", str(p.get("blocksize", 4))]
    if p.get("maxevents") is not None: cmd += ["-m", str(p["maxevents"])]
    cmd += [str(x) for x in p.get("extra_args", [])]
    save_json(out / "command.json", {"cmd": cmd, "params": p, "manifest": manifest})
    run_cmd(cmd, cwd=repo, dry_run=cfg["general"].get("dry_run", False), log_path=common_log(work, "pix2nvs", manifest["name"]))
    events_dir = repo / "Events"
    if events_dir.exists() and not cfg["general"].get("dry_run", False):
        archived = out / "Events"
        if archived.exists(): shutil.rmtree(archived)
        shutil.copytree(events_dir, archived)

def write_summary(cfg: Dict[str, Any]) -> None:
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    summary = {"created_at": datetime.now().isoformat(), "prepared": [], "outputs": {}}
    for p in prepared_sequences(cfg):
        summary["prepared"].append(load_manifest(p))
    for sim in ["v2e", "vid2e", "iebcs", "dvs_voltmeter", "pix2nvs"]:
        out = work / "simulated_events" / sim
        if out.exists():
            summary["outputs"][sim] = [str(x) for x in sorted(out.iterdir()) if x.is_dir()]
    save_json(work / "pipeline_summary.json", summary)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", default=None, choices=["all", "v2e", "vid2e", "iebcs", "dvs_voltmeter", "pix2nvs"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_yaml(Path(args.config))
    if args.dry_run:
        cfg["general"]["dry_run"] = True
    work = Path(cfg["paths"]["work_dir"]).expanduser()
    work.mkdir(parents=True, exist_ok=True)
    save_json(work / "pipeline_config_used.json", cfg)

    if args.prepare:
        seqs = discover_sequences(cfg)
        if not seqs:
            raise SystemExit("Aucune séquence RGB/vidéo détectée. Vérifie paths.vivid_output.")
        print(f"[INFO] {len(seqs)} séquence(s) détectée(s).")
        for seq in seqs:
            prepare_sequence(seq, cfg)

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
                runners[sim](cfg, prepared)

    write_summary(cfg)
    print(f"\n[FINI] Résumé : {work / 'pipeline_summary.json'}")

if __name__ == "__main__":
    main()
