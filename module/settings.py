"""
This module is operating 'settings.json' file, that is responsible for the scripts execution.
"""

import os, json

class Settings:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))

    def load(self):
        with open(f'{self.current_dir}/settings.json', 'r') as f:
            settings_json = json.load(f)
        return settings_json

