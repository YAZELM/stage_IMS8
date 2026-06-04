# Pipeline dataset ViViD++

Cette partie transforme les fichiers `.bag` ViViD++ en une structure simple utilisée par les simulateurs.

## Entrée

```text
data/raw_bags/*.bag
```

## Commande

```bash
python dataset_pipeline/run_pipeline.py data/raw_bags --out data/outputs
```

## Sortie

```text
data/outputs/<sequence>/
├── frames_rgb/
├── events/
├── timestamps/
└── videos/
```

## Scripts

### `run_pipeline.py`

Script principal. Il lance successivement :

```text
extract_rgb.py
extract_events.py
frames_to_video.py
```

### `extract_rgb.py`

Extrait les images RGB.

Sorties :

```text
frames_rgb/
timestamps/rgb_timestamps.txt
```

### `extract_events.py`

Extrait les événements DVS réels.

Sortie :

```text
events/events_xytp_000000.npz
```

Format sauvegardé :

```text
x, y, t, p
```

### `frames_to_video.py`

Crée une vidéo RGB à partir des frames.

Sortie :

```text
videos/rgb.mp4
```

### `inspect_bag.py`

Affiche les topics disponibles dans un fichier `.bag`.

Commande :

```bash
python dataset_pipeline/inspect_bag.py data/raw_bags/sequence.bag
```

## Topics

Par défaut, le script cherche automatiquement les topics RGB et DVS.

Les topics peuvent être fixés manuellement :

```bash
python dataset_pipeline/run_pipeline.py data/raw_bags/sequence.bag \
  --out data/outputs \
  --rgb_topic /camera/image_color \
  --event_topic /dvs/events
```
