"""
This module is operating 'settings.json' file, that is responsible for the scripts execution.
"""


import json
import logging
import os

log = logging.getLogger("main.utils.settings")


class Settings:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(self, script_type: str) -> dict:
        with open(f"{self.current_dir}/data/settings_{script_type}.json", "r") as f:
            settings = json.load(f)

        return settings

    def dump(self, settings: dict, script_type: str) -> None:
        with open(f"{self.current_dir}/data/settings_{script_type}.json", "w") as f:
            json.dump(settings, f, indent=4)
