"""
This module is operating 'instruments.json' file, that is responsible for storing BEAR/BULL instruments.
"""


import os
import json
import logging
import yfinance as yf


log = logging.getLogger("main.instruments")


class Instrument:
    def __init__(self, trading_multiplier):
        self.ids_dict = self.get_id(trading_multiplier)

    def get_id(self, trading_multiplier):
        log.info(
            f"Getting instrument_ids from DT_instruments.json for trading_multiplier={trading_multiplier}"
        )

        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        with open(f"{current_dir}/data/instruments_DT.json", "r") as f:
            instruments_json = json.load(f)

        instrument_ids_dict = {
            "MONITORING": instruments_json['MONITORING'],
            "TRADING": instruments_json['TRADING'][str(trading_multiplier)]}

        return instrument_ids_dict
