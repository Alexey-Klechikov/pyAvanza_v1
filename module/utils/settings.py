"""
This module is operating 'settings.json' file, that is responsible for the scripts execution.
"""


import os
import json
import logging


log = logging.getLogger("main.settings")


class Settings:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(self):
        log.info("Loading settings.json")

        with open(f"{self.current_dir}/data/settings.json", "r") as f:
            settings_json = json.load(f)

        return settings_json

    def dump(self, settings_json):
        log.info("Dump settings.json")

        with open(f"{self.current_dir}/data/settings.json", "w") as f:
            json.dump(settings_json, f, indent=4)

    def read(self, account):
        log.info(f"Read settings.json")

        settings_json = self.load()[account]

        message_list = list()

        def _traverse_dict(value, level):
            if isinstance(value, dict):
                for k, v in value.items():
                    message_list.append(f'{">" * level} {k}')
                    _traverse_dict(v, level + 1)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    message_list.append(f'\n{">" * level} {i}')
                    _traverse_dict(item, level + 1)
            else:
                message_list.append(f'{">" * level} [{value}]')

        for key in settings_json.keys():
            message_list.append(f"> {key}")
            _traverse_dict(settings_json[key], level=2)

        return "\n".join(message_list)

    def write(self, parameter, value):
        log.info(f"Write settings.json")

        keys_path_list = parameter.split(".")
        settings_json = self.load()

        updated_dict = settings_json
        for key in keys_path_list[:-1]:
            if key in updated_dict:
                updated_dict = updated_dict[key]
            else:
                return f"Invalid key: {key}"

        if keys_path_list[-1] in updated_dict:
            updated_dict[keys_path_list[-1]] = value
        else:
            return f"Invalid key: {keys_path_list[-1]}"

        self.dump(settings_json)
