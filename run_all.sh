#!/usr/bin/env bash
set -e

CONFIG=${CONFIG:-config/pipeline_config.yaml}
BAGS=${BAGS:-data/raw_bags}
SIMS=${SIMS:-all}

if [ ! -f "$CONFIG" ]; then
  echo "[ERREUR] Fichier de configuration introuvable : $CONFIG"
  echo "Créer la configuration avec : cp config/pipeline_config.example.yaml config/pipeline_config.yaml"
  exit 1
fi

echo "=== Vérification du projet ==="
python scripts/00_check_project.py --config "$CONFIG"

if [ "${EXTRACT_DATASET:-0}" = "1" ]; then
  echo "=== Extraction du dataset ViViD++ ==="
  python dataset_pipeline/run_pipeline.py "$BAGS" --out data/outputs
fi

echo "=== Préparation des séquences ==="
python run_vivid_event_pipeline.py --config "$CONFIG" --prepare

echo "=== Lancement des simulateurs ==="
if [ "$SIMS" = "all" ]; then
  python run_vivid_event_pipeline.py --config "$CONFIG" --run all
else
  for sim in $SIMS; do
    python run_vivid_event_pipeline.py --config "$CONFIG" --run "$sim"
  done
fi

echo "=== Conversion vers le format AER NPZ ==="
python scripts/02_convert_simulator_outputs_to_aer_npz.py --config "$CONFIG"

echo "=== Préparation des événements réels ViViD++ ==="
python scripts/03_prepare_vivid_real_events_to_aer_npz.py --config "$CONFIG"

echo "=== Comparaison finale ==="
python scripts/04_compare_fundamental_metrics.py runs/aer_npz runs/comparison

echo "=== Pipeline terminée ==="
echo "Résultats disponibles dans : runs/comparison/"
