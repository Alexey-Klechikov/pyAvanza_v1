"""
This module is operating 'settings.json' file, that is responsible for the scripts execution.
"""


import os
import json
import logging


log = logging.getLogger("main.utils.settings")


class Settings:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(self) -> dict:
        log.info("Loading settings.json")

        with open(f"{self.current_dir}/data/settings.json", "r") as f:
            settings = json.load(f)

        return settings

    def dump(self, settings: dict) -> None:
        log.info("Dump settings.json")

        with open(f"{self.current_dir}/data/settings.json", "w") as f:
            json.dump(settings, f, indent=4)

    def read(self, account: str) -> str:
        log.info(f"Read settings.json")

        settings = self.load()[account]

        messages = list()

        def _traverse_dict(value, level):
            if isinstance(value, dict):
                for k, v in value.items():
                    messages.append(f'{">" * level} {k}')
                    _traverse_dict(v, level + 1)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    messages.append(f'\n{">" * level} {i}')
                    _traverse_dict(item, level + 1)
            else:
                messages.append(f'{">" * level} [{value}]')

        for key in settings.keys():
            messages.append(f"> {key}")
            _traverse_dict(settings[key], level=2)

        return "\n".join(messages)
