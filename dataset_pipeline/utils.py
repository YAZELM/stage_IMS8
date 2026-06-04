"""Fonctions utilitaires pour la lecture des bags et l’organisation des sorties."""
from pathlib import Path
import json
import shutil                                                                                    
import cv2
import numpy as np
from rosbags.highlevel import AnyReader                                                                             


def seq_name_from_bag(bag_path):                                     
    return Path(bag_path).stem                                                                


def sequence_dirs(out_root, seqname):                                                                                  
    seq_dir = Path(out_root) / seqname
    dirs = {
        "seq": seq_dir,
        "frames": seq_dir / "frames_rgb",
        "timestamps": seq_dir / "timestamps",
        "events": seq_dir / "events",
        "videos": seq_dir / "videos",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)                                              
    return dirs


def write_json(path, data):                                                                           
    with open(path, "w", encoding="utf-8") as f:                                          
        json.dump(data, f, indent=4)


def reset_dir(path):                                                                 
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)                                       
    path.mkdir(parents=True, exist_ok=True)


def open_bag(bag_path):
    return AnyReader([Path(bag_path)])                                                                


def topic_type(connection):
    return connection.msgtype.replace("/msg/", "/")


def stamp_to_sec(stamp):                                                                    
    if hasattr(stamp, "sec"):
        return stamp.sec + stamp.nanosec * 1e-9
    return stamp.secs + stamp.nsecs * 1e-9


def read_topic(reader, topic):                              
    connections = [c for c in reader.connections if c.topic == topic]                                                  
    for connection, _, raw_data in reader.messages(connections=connections):
        yield reader.deserialize(raw_data, connection.msgtype)                                                               


def find_topic(reader, kind, requested=None):
    topics = {connection.topic for connection in reader.connections}

    if requested:
        if requested not in topics:
            raise ValueError(f"Topic demande introuvable: {requested}")
        if kind == "rgb" and any(w in requested.lower() for w in ("thermal", "depth", "dvs", "event")):
            raise ValueError(f"Ce topic n'est pas RGB: {requested}")
        return requested

    if kind == "rgb":
        preferred = ("/camera/image_color", "/rgb/image")
        for topic in preferred:
            if topic in topics:
                return topic

    for connection in reader.connections:
        name = connection.topic.lower()
        msg_type = topic_type(connection)
        blocked = ("thermal", "depth", "dvs", "event")
        is_rgb_name = "rgb" in name or "color" in name or "colour" in name
        is_image = msg_type.endswith("sensor_msgs/Image")
        if kind == "rgb" and is_image and is_rgb_name and not any(w in name for w in blocked):
            return connection.topic
        if kind == "events" and connection.topic == "/dvs/events":
            return connection.topic
        if kind == "events" and "EventArray" in msg_type:
            return connection.topic

    raise ValueError(f"Topic {kind} introuvable")


def image_to_bgr(msg):                                      
    encoding = msg.encoding.lower()

    if encoding == "rgb8":
        image = np.asarray(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if encoding == "bgr8":
        return np.asarray(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)

    raise ValueError(f"Le topic choisi n'est pas RGB 8 bits: {msg.encoding}")


def estimate_fps_from_frame_names(frames_dir):                                                                                                
    frames = sorted(Path(frames_dir).glob("*.png"))
    if len(frames) < 2:
        return 30.0
    times = np.array([float(p.stem) for p in frames], dtype=np.float64)
    dt = np.diff(times)
    dt = dt[dt > 0]
    if len(dt) == 0:
        return 20.0
    return float(1.0 / np.median(dt))
