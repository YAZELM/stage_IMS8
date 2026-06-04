# Installation des simulateurs

Les simulateurs doivent être installés séparément. Ils ne sont pas inclus dans ce dépôt.

Structure recommandée :

```text
external/
├── v2e/
├── rpg_vid2e/
├── IEBCS/
├── DVS-Voltmeter/
└── PIX2NVS/
```

Les chemins sont à renseigner dans :

```text
config/pipeline_config.yaml
```

## v2e

Entrée utilisée :

```text
video.mp4
```

## Vid2E

Entrée utilisée :

```text
frames RGB
```

La pipeline utilise une étape d’upsampling, puis une étape de génération d’événements.

## IEBCS

IEBCS est lancé avec :

```text
adapters/run_iebcs_sequence.py
```

Entrées :

```text
frames RGB
timestamps_us.txt
```

Sorties :

```text
events.txt
events.dat
```

## DVS-Voltmeter

Entrées :

```text
frames RGB
info.txt
```

## PIX2NVS

Entrée :

```text
video.mp4
```

PIX2NVS peut nécessiter une compilation C++ selon l’installation locale.
