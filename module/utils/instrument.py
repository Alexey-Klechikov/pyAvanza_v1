"""
This module is operating 'instruments.json' file, that is responsible for storing BEAR/BULL instruments.
"""


import os
import json
import logging
import yfinance as yf
from typing import Union


log = logging.getLogger("main.utils.instruments")


class Instrument:
    def __init__(self, trading_multiplier: int):
        self.ids = self.get_ids(trading_multiplier)

    def get_ids(self, trading_multiplier: Union[int, str]) -> dict:
        log.info(
            f"Getting instrument_ids from instruments_DT.json for trading_multiplier={trading_multiplier}"
        )

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(f"{current_dir}/data/instruments_DT.json", "r") as f:
            instruments = json.load(f)

        ids = {
            "MONITORING": instruments['MONITORING'],
            "TRADING": instruments['TRADING'][str(trading_multiplier)]}

        return ids
