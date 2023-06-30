"""
This module is operating 'state.json' file, that is responsible for the state storage.
"""


import json
import logging
import os

log = logging.getLogger("main.utils.state")


class State:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(self, script_type: str) -> dict:
        state = {}
        with open(f"{self.current_dir}/data/state.json", "r") as f:
            state = json.load(f)

        return state.get(script_type, {})

    def dump(self, state_for_script_type: dict, script_type: str) -> None:
        state = {}
        with open(f"{self.current_dir}/data/state.json", "r") as f:
            state = json.load(f)

        state[script_type] = state_for_script_type

        with open(f"{self.current_dir}/data/state.json", "w") as f:
            json.dump(state, f, indent=4)
