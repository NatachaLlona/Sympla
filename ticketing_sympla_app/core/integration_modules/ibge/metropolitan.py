"""Pinned official metropolitan scope; demographic observations remain Census 2022."""
import json
from functools import lru_cache
from pathlib import Path

PRESET = 'capital_metropolitan_areas_2025'


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('metropolitan_areas_2025.json').read_text(encoding='utf-8'))


def municipality_codes():
    return {row['code'] for row in catalog()['municipalities']}
