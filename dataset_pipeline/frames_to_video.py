"""Création d’une vidéo RGB à partir des frames extraites."""
import argparse
from pathlib import Path
import cv2
from utils import estimate_fps_from_frame_names

def frames_to_video(seq_dir, fps="auto"):
    seq_dir = Path(seq_dir)
    frames_dir = seq_dir / "frames_rgb"
    videos_dir = seq_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    video_path = videos_dir / "rgb.mp4"
    frames = sorted(frames_dir.glob("*.png"))

    if len(frames) == 0:
        raise RuntimeError(f"No PNG frames found in {frames_dir}")

    fps_value = estimate_fps_from_frame_names(frames_dir) if fps == "auto" else float(fps)

    first = cv2.imread(str(frames[0]))
    if first is None:
        raise RuntimeError(f"Cannot read first frame: {frames[0]}")

    h, w = first.shape[:2]

    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps_value,
        (w, h),
    )

    for frame_path in frames:
        img = cv2.imread(str(frame_path))
        if img is not None:
            writer.write(img)

    writer.release()

    print("\n[VIDEO] Saved:", video_path)
    print("[VIDEO] FPS:", round(fps_value, 3))
    print("[VIDEO] Resolution:", w, "x", h)
    print("[VIDEO] Frames:", len(frames))

    return {
        "video_path": str(video_path),
        "fps": fps_value,
        "width": w,
        "height": h,
        "frames": len(frames),
    }


def main():
    parser = argparse.ArgumentParser(description="Convert extracted RGB frames to MP4 video")
    parser.add_argument("seq_dir")
    parser.add_argument("--fps", default="auto")
    args = parser.parse_args()

    frames_to_video(args.seq_dir, fps=args.fps)


if __name__ == "__main__":
    main()
