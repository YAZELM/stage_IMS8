"""Pipeline d’extraction ViViD++ : RGB, événements DVS et vidéo."""
import argparse
from pathlib import Path
from extract_rgb import extract_rgb
from extract_events import extract_events
from frames_to_video import frames_to_video
from utils import seq_name_from_bag, write_json


def run_one_bag(args, bag_path):
    bag_path = Path(bag_path)
    seqname = seq_name_from_bag(bag_path)
    seq_dir = Path(args.out) / seqname

    print("\n" + "=" * 60)
    print("SEQUENCE:", seqname)
    print("=" * 60)

    rgb_meta = extract_rgb(bag_path, args.out, args.rgb_topic)
    event_meta = extract_events(bag_path, args.out, args.event_topic)
    video_meta = frames_to_video(seq_dir, fps=args.fps)

    summary = {
        "sequence": seqname,
        "bag_file": str(bag_path),
        "rgb": rgb_meta,
        "events": event_meta,
        "video": video_meta,
    }

    write_json(seq_dir / "timestamps" / "metadata.json", summary)

    print("\n[DONE]", seqname)
    print("[OUT]", seq_dir)


def collect_bags(inputs):
    bags = []

    for item in inputs:
        path = Path(item)

        if path.is_file() and path.suffix == ".bag":
            bags.append(path)
        elif path.is_dir():
            bags.extend(sorted(path.rglob("*.bag")))
        else:
            print("[WARN] ignored:", path)

    seen = set()
    unique_bags = []
    for bag in bags:
        resolved = bag.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_bags.append(bag)

    return unique_bags


def main():
    parser = argparse.ArgumentParser(description="Complete modular ViViD++ extraction pipeline")

    parser.add_argument("inputs", nargs="+", help="One or more .bag files or folders containing .bag files")
    parser.add_argument("--out", default="outputs")

    parser.add_argument("--rgb_topic", default=None)
    parser.add_argument("--event_topic", default=None)

    parser.add_argument("--fps", default="auto")

    args = parser.parse_args()

    bags = collect_bags(args.inputs)
    if not bags:
        raise SystemExit("No .bag files found.")

    print("[PIPELINE] Bags found:", len(bags))
    for bag in bags:
        run_one_bag(args, bag)


if __name__ == "__main__":
    main()
