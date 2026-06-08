#!/usr/bin/env python

"""Extraction des evenements DVS reels depuis un fichier ViViD++ .bag.



Le script lit les paquets d'evenements du bag, les convertit au format commun

x, y, t, p, puis les sauvegarde en fichiers NPZ. Les sauvegardes par fenetre

evitent de garder toute une tres longue sequence en memoire.

"""



import argparse

import time

from pathlib import Path



import numpy as np



from utils import find_topic, open_bag, read_topic, reset_dir, seq_name_from_bag, sequence_dirs, stamp_to_sec, write_json





def elapsed_text(seconds):

    # Affichage lisible du temps de traitement pour suivre les longues extractions.

    minutes, sec = divmod(int(seconds), 60)

    hours, minutes = divmod(minutes, 60)

    return f"{hours:02d}:{minutes:02d}:{sec:02d}"





def save_events_npz(path, x, y, t, p, width, height):

    # Le NPZ contient uniquement les colonnes AER utiles et la resolution.

    # Le champ format documente explicitement l'ordre des tableaux.

    np.savez(

        path,

        x=x,

        y=y,

        t=t,

        p=p,

        width=np.array(width if width is not None else -1),

        height=np.array(height if height is not None else -1),

        format=np.array("x,y,t,p"),

    )





def event_packet_to_arrays(msg, first_ts):

    # Un message contient souvent un paquet d'evenements. On le transforme en

    # tableaux NumPy pour pouvoir concatener et sauvegarder efficacement.

    events = msg.events

    n = len(events)



    if first_ts is None:

        first_ts = stamp_to_sec(events[0].ts) if hasattr(events[0], "ts") else stamp_to_sec(msg.header.stamp)



    x = np.empty(n, dtype=np.uint16)

    y = np.empty(n, dtype=np.uint16)

    t = np.empty(n, dtype=np.float16)

    p = np.empty(n, dtype=np.uint8)

    last_ts = first_ts



    # Certains formats donnent un timestamp par evenement. Dans ce cas on garde

    # la dynamique fine du paquet au lieu d'utiliser le timestamp global du message.

    if hasattr(events[0], "ts"):

        for i, event in enumerate(events):

            event_ts = event.ts.sec + event.ts.nanosec * 1e-9

            x[i] = event.x

            y[i] = event.y

            t[i] = event_ts - first_ts

            p[i] = 1 if event.polarity else 0

            last_ts = event_ts

    else:

        # Si le bag ne fournit pas de timestamp individuel, tous les evenements

        # du paquet recoivent le timestamp du message. C'est moins fin, mais explicite.

        event_ts = stamp_to_sec(msg.header.stamp)

        t.fill(event_ts - first_ts)

        for i, event in enumerate(events):

            x[i] = event.x

            y[i] = event.y

            p[i] = 1 if event.polarity else 0

        last_ts = event_ts



    return x, y, t, p, first_ts, last_ts





def save_buffers(path, xs, ys, ts, ps, width, height):

    # Les buffers sont concatennes seulement au moment de l'ecriture pour limiter

    # les réallocations pendant la lecture du bag.

    save_events_npz(

        path,

        np.concatenate(xs),

        np.concatenate(ys),

        np.concatenate(ts),

        np.concatenate(ps),

        width,

        height,

    )





def extract_events(

    bag_path,

    out_root="outputs",

    event_topic=None,

    window_minutes=10.0,

):

    # Chaque sequence repart sur un dossier events propre pour que les anciens

    # fichiers NPZ ne se melangent pas avec une nouvelle extraction.

    bag_path = Path(bag_path)

    seqname = seq_name_from_bag(bag_path)

    dirs = sequence_dirs(out_root, seqname)

    reset_dir(dirs["events"])



    xs, ys, ts, ps = [], [], [], []

    window_files = []

    window_index = 0

    window_seconds = float(window_minutes) * 60.0

    start_time = time.time()

    next_save_time = start_time + window_seconds



    event_packets = 0

    total_events = 0

    width = None

    height = None

    first_ts = None

    last_ts = None



    print("\n[EVENTS] Processing:", bag_path.name)

    print("[EVENTS] Output:", dirs["events"])

    print("[EVENTS] Save every minutes:", window_minutes)



    with open_bag(bag_path) as bag:

       

        event_topic = find_topic(bag, "events", event_topic)

        print("[EVENTS] Topic:", event_topic)



        for msg in read_topic(bag, event_topic):

            event_packets += 1

            width = msg.width

            height = msg.height



            if not hasattr(msg, "events") or len(msg.events) == 0:

                continue



            x, y, t, p, first_ts, last_ts = event_packet_to_arrays(msg, first_ts)

            xs.append(x)

            ys.append(y)

            ts.append(t)

            ps.append(p)

            total_events += len(t)



            # La sauvegarde periodique se base sur le temps de calcul, pas sur le

            # temps de la sequence. C'est surtout une protection memoire pendant l'extraction. Car dans mon cas j'étais limite par la RAM avant d'être limité par le temps de calcul. Mais cela peut aussi aider a suivre l'avancement de l'extraction sur les longues sequences.

            now = time.time()

            if len(ts) > 0 and now >= next_save_time:

                window_path = dirs["events"] / f"events_xytp_{window_index:06d}.npz"

                save_buffers(window_path, xs, ys, ts, ps, width, height)

                window_files.append(str(window_path))

                window_index += 1



                xs, ys, ts, ps = [], [], [], []

                next_save_time = now + window_seconds



                print(f"[EVENTS] saved: {window_path} | elapsed: {elapsed_text(now - start_time)}", flush=True)



            if event_packets % 100 == 0:

                print(

                    f"[EVENTS] elapsed: {elapsed_text(time.time() - start_time)} | "

                    f"packets: {event_packets} | events: {total_events}",

                    flush=True,

                )



    # Le dernier buffer est toujours ecrit, même si la fenetre temporelle n'est

    # pas complete. Cela evite de perdre la fin de la sequence. 

    if len(ts) > 0:

        window_path = dirs["events"] / f"events_xytp_{window_index:06d}.npz"

        save_buffers(window_path, xs, ys, ts, ps, width, height)

        window_files.append(str(window_path))

        print(f"[EVENTS] saved: {window_path} | elapsed: {elapsed_text(time.time() - start_time)}", flush=True)



    elapsed_seconds = time.time() - start_time



    # Les metadonnees servent de trace experimentale: topic utilise, resolution,

    # duree, nombre d'evenements et liste exacte des fichiers produits.

    metadata = {

        "sequence": seqname,

        "bag_file": str(bag_path),

        "event_topic": event_topic,

        "event_packets": event_packets,

        "total_events": int(total_events),

        "event_width": int(width) if width is not None else None,

        "event_height": int(height) if height is not None else None,

        "first_event_timestamp": first_ts,

        "last_event_timestamp": last_ts,

        "event_format": "x,y,t,p",

        "save_every_minutes": float(window_minutes),

        "elapsed_seconds": elapsed_seconds,

        "npz_count": len(window_files),

        "npz_files": window_files,

    }



    write_json(dirs["events"] / "event_metadata.json", metadata)



    print("[EVENTS] Done.")

    print("[EVENTS] Elapsed:", elapsed_text(elapsed_seconds))

    print("[EVENTS] Packets:", event_packets)

    print("[EVENTS] Events:", total_events)

    print("[EVENTS] NPZ files:", len(window_files))



    return metadata





def main():



    parser = argparse.ArgumentParser(description="Extract DVS events from a ViViD++ ROS bag")

    parser.add_argument("bag")

    parser.add_argument("--out", default="outputs")

    parser.add_argument("--event_topic", default="/dvs/events")

    parser.add_argument("--window_minutes", type=float, default=10.0)

    args = parser.parse_args()



    extract_events(

        bag_path=args.bag,

        out_root=args.out,

        event_topic=args.event_topic,

        window_minutes=args.window_minutes,

    )





if __name__ == "__main__":

    main()

