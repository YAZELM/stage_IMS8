"""Fonctions communes de la pipeline ViViD++.

Ce module regroupe les petits outils partages par les scripts d'extraction:
creation des dossiers, lecture des bags ROS, choix des topics et conversion
des images. Le but est d'eviter de dupliquer ces decisions dans chaque script.
"""
from pathlib import Path
import json
import shutil

import cv2
import numpy as np
from rosbags.highlevel import AnyReader


def seq_name_from_bag(bag_path):
    # Le nom de sequence vient du nom du fichier .bag. Cela garde la meme
    # nomenclature partout dans les sorties.
    return Path(bag_path).stem


def sequence_dirs(out_root, seqname):
    # Toutes les sorties d'une sequence sont rangees sous le meme dossier:
    # frames, timestamps, evenements et video reconstruite.
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
    # Les metadonnees sont ecrites en JSON lisible pour pouvoir auditer les
    # extractions sans relancer les scripts.
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def reset_dir(path):
    # On vide seulement le dossier demande. C'est utile pour les events, car une
    # nouvelle extraction ne doit pas melanger anciens et nouveaux fichiers NPZ.
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def open_bag(bag_path):
    # AnyReader permet de lire les bags ROS1 sans lancer un environnement ROS complet.
    return AnyReader([Path(bag_path)])


def topic_type(connection):
    # Les types ROS peuvent apparaitre avec /msg/. On normalise cette ecriture
    # pour simplifier les tests de type plus bas.
    return connection.msgtype.replace("/msg/", "/")


def stamp_to_sec(stamp):
    # Les bags ne portent pas tous les champs de timestamp sous le meme nom.
    # Cette fonction accepte les deux conventions courantes: sec/nanosec et secs/nsecs.
    if hasattr(stamp, "sec"):
        return stamp.sec + stamp.nanosec * 1e-9
    return stamp.secs + stamp.nsecs * 1e-9


def read_topic(reader, topic):
    # On filtre explicitement les connexions du topic choisi, puis on deserialise
    # chaque message au moment ou il est lu.
    connections = [c for c in reader.connections if c.topic == topic]
    for connection, _, raw_data in reader.messages(connections=connections):
        yield reader.deserialize(raw_data, connection.msgtype)


def find_topic(reader, kind, requested=None):
    # Si l'utilisateur impose un topic, on le respecte mais on verifie qu'il existe.
    # Pour le RGB, on evite aussi les topics thermiques, depth ou DVS par securite.
    topics = {connection.topic for connection in reader.connections}

    if requested:
        if requested not in topics:
            raise ValueError(f"Topic demande introuvable: {requested}")
        if kind == "rgb" and any(w in requested.lower() for w in ("thermal", "depth", "dvs", "event")):
            raise ValueError(f"Ce topic n'est pas RGB: {requested}")
        return requested

    # Quelques noms reviennent souvent dans les bags. On les teste d'abord pour
    # eviter de choisir un topic moins pertinent quand plusieurs images existent.
    if kind == "rgb":
        preferred = ("/camera/image_color", "/rgb/image")
        for topic in preferred:
            if topic in topics:
                return topic

    # Sinon on choisit automatiquement en croisant le nom du topic et le type ROS.
    # Cette heuristique reste volontairement stricte pour limiter les erreurs silencieuses.
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
    # OpenCV travaille en BGR. On convertit donc rgb8 vers BGR, et on laisse bgr8
    # tel quel. Les autres encodages sont refuses pour ne pas comparer des images mal decodees.
    encoding = msg.encoding.lower()

    if encoding == "rgb8":
        image = np.asarray(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if encoding == "bgr8":
        return np.asarray(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)

    raise ValueError(f"Le topic choisi n'est pas RGB 8 bits: {msg.encoding}")


def estimate_fps_from_frame_names(frames_dir):
    # Les noms de frames contiennent les timestamps. La mediane des delais donne
    # un FPS robuste aux petites irregularites et aux rares valeurs aberrantes.
    frames = sorted(Path(frames_dir).glob("*.png"))
    if len(frames) < 2:
        return 30.0
    times = np.array([float(p.stem) for p in frames], dtype=np.float64)
    dt = np.diff(times)
    dt = dt[dt > 0]
    if len(dt) == 0:
        return 20.0
    return float(1.0 / np.median(dt))
