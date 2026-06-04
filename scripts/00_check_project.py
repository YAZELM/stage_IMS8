#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# Vérifie rapidement que les chemins principaux du projet sont configurés.
import argparse
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    raise SystemExit('PyYAML is missing. Install with: pip install pyyaml')


def check_path(label: str, path: Path, required: bool, errors: list[str], warnings: list[str]) -> None:
    if path.exists():
        print(f'[OK] {label}: {path}')
    else:
        msg = f'{label} not found: {path}'
        if required:
            errors.append(msg)
            print(f'[ERR] {msg}')
        else:
            warnings.append(msg)
            print(f'[WARN] {msg}')


def main() -> int:
    ap = argparse.ArgumentParser(description='Check project layout and configuration paths.')
    ap.add_argument('--config', type=Path, default=Path('config/pipeline_config.yaml'))
    ap.add_argument('--strict', action='store_true', help='Fail if simulator repositories are missing.')
    args = ap.parse_args()

    root = Path.cwd()
    errors: list[str] = []
    warnings: list[str] = []

    check_path('project root', root, True, errors, warnings)
    check_path('config', args.config, True, errors, warnings)
    check_path('runner', root / 'run_vivid_event_pipeline.py', True, errors, warnings)
    check_path('IEBCS adapter', root / 'adapters' / 'run_iebcs_sequence.py', True, errors, warnings)
    check_path('converter', root / 'scripts' / '02_convert_simulator_outputs_to_aer_npz.py', True, errors, warnings)
    check_path('real ViViD++ converter', root / 'scripts' / '03_prepare_vivid_real_events_to_aer_npz.py', True, errors, warnings)
    check_path('comparison script', root / 'scripts' / '04_compare_vivid_vs_sim_scientific_log.py', True, errors, warnings)

    if not args.config.exists():
        print('\n[DONE] Configuration file is missing.')
        return 1

    cfg = yaml.safe_load(args.config.read_text(encoding='utf-8'))
    paths = cfg.get('paths', {})

    vivid_output = Path(paths.get('vivid_output', '')).expanduser()
    work_dir = Path(paths.get('work_dir', '')).expanduser()
    check_path('vivid_output', vivid_output, False, errors, warnings)
    print(f'[INFO] work_dir: {work_dir}')

    for tool in ['ffmpeg', 'ffprobe']:
        if shutil.which(tool):
            print(f'[OK] {tool}: {shutil.which(tool)}')
        else:
            errors.append(f'{tool} not found in PATH')
            print(f'[ERR] {tool} not found in PATH')

    repos = paths.get('repos', {})
    for name, value in repos.items():
        check_path(f'repo {name}', Path(value).expanduser(), args.strict, errors, warnings)

    pythons = paths.get('pythons', {})
    for name, value in pythons.items():
        if value == 'python' or shutil.which(value) or Path(value).expanduser().exists():
            print(f'[OK] python {name}: {value}')
        else:
            warnings.append(f'Python for {name} not found: {value}')
            print(f'[WARN] Python for {name} not found: {value}')

    print('\nSummary')
    print(f'  errors  : {len(errors)}')
    print(f'  warnings: {len(warnings)}')

    if errors:
        print('\nErrors:')
        for e in errors:
            print(f'  - {e}')
        return 1

    if warnings:
        print('\nWarnings:')
        for w in warnings:
            print(f'  - {w}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
