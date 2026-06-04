"""Extraction des images RGB et des timestamps depuis un fichier ViViD++ .bag."""
import argparse                                             
from pathlib import Path
import cv2
from utils import (
    find_topic,
    image_to_bgr,
    open_bag,
    read_topic,
    seq_name_from_bag,
    sequence_dirs,
    stamp_to_sec,
    write_json,
)

def extract_rgb(bag_path, out_root="outputs", rgb_topic=None):                                       
    bag_path = Path(bag_path)                   
    seqname = seq_name_from_bag(bag_path) 
    dirs = sequence_dirs(out_root, seqname)

    frames_dir = dirs["frames"]                                               
    timestamps_path = dirs["timestamps"] / "rgb_timestamps.txt"                       

    count = 0
    first_ts = None                                                         
    last_ts = None
    width = None
    height = None

    print("\n[RGB] Processing:", bag_path.name)                                                          
    with open_bag(bag_path) as bag, open(timestamps_path, "w") as f_ts:
        rgb_topic = find_topic(bag, "rgb", rgb_topic)

        print("[RGB] Topic:", rgb_topic)
        print("[RGB] Output:", frames_dir)

        f_ts.write("index,timestamp,frame_name\n")

        for msg in read_topic(bag, rgb_topic):                                                    
            timestamp = stamp_to_sec(msg.header.stamp)
            img = image_to_bgr(msg)

            height, width = img.shape[:2]

            frame_name = f"{timestamp:.6f}.png"                                   
            frame_path = frames_dir / frame_name
            cv2.imwrite(str(frame_path), img)                                      

            f_ts.write(f"{count},{timestamp:.6f},{frame_name}\n")

            if first_ts is None:
                first_ts = timestamp
            last_ts = timestamp
            count += 1

            if count % 100 == 0:
                print(f"[RGB] saved frames: {count}", flush=True)                                                                               

    metadata = {                                            
        "sequence": seqname,
        "bag_file": str(bag_path),
        "rgb_topic": rgb_topic,
        "rgb_frames_saved": count,
        "rgb_width": width,
        "rgb_height": height,
        "first_rgb_timestamp": first_ts,
        "last_rgb_timestamp": last_ts,
    }

    write_json(dirs["timestamps"] / "rgb_metadata.json", metadata)

    print("[RGB] Done.")
    print("[RGB] Frames saved:", count)

    return metadata


def main():
    parser = argparse.ArgumentParser(description="Extract RGB frames from a ViViD++ ROS bag")
    parser.add_argument("bag")
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--rgb_topic", default=None)
    args = parser.parse_args()

    extract_rgb(args.bag, args.out, args.rgb_topic)


if __name__ == "__main__":
    main()
