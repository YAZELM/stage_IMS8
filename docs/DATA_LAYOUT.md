# Organisation des dossiers

## Données brutes

```text
data/raw_bags/
└── sequence.bag
```

## Dataset extrait

```text
data/outputs/<sequence>/
├── frames_rgb/
├── events/
├── timestamps/
└── videos/
```

## Sorties des simulateurs

```text
runs/simulated_events/
├── v2e/
├── vid2e/
├── iebcs/
├── dvs_voltmeter/
└── pix2nvs/
```

## Format AER commun

```text
runs/aer_npz/
├── vivid/
├── v2e/
├── vid2e/
├── iebcs/
├── dvs_voltmeter/
└── pix2nvs/
```

Chaque fichier contient :

```text
x, y, t, p
```

## Résultats

```text
runs/comparison/
├── metrics_vivid_vs_sim.csv
├── summary_by_simulator.csv
├── aer_format_check.csv
├── load_errors.csv
└── figures/
```
