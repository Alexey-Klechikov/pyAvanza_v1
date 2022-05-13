"""
This module is used for manual runs (checkups, improvements, tests)
"""

"""
import logging, keyring, time

import pandas as pd

from pprint import pprint

from avanza import Avanza, OrderType
from module.utils import Context, Strategy, Plot, Settings, Logger

log = logging.getLogger('main')


def get_ava_index():

    def _get_ctx(user):
        log.info('Getting context')

        i = 1
        while True:
            try:
                ctx = Avanza({
                    'username': keyring.get_password(user, 'un'),
                    'password': keyring.get_password(user, 'pass'),
                    'totpSecret': keyring.get_password(user, 'totp')})
                break
            except Exception as e:
                log.error(e)
                i += 1
                time.sleep(i*2)   

        return ctx

    ava = _get_ctx('ava_elbe')
"""

"""
import asyncio, keyring, time
from datetime import datetime
from avanza import Avanza, ChannelType

def callback(data):
    fields_list = ['closingPrice', 'highestPrice', 'lowestPrice', 'lastPrice', 'change', 'changePercent', 'updated']
    data_dict = {k:v for k,v in data['data'].items() if k in fields_list}  
    data_dict['updated'] = str(datetime.fromtimestamp(int(str(data_dict['updated'])[:-3])))

    print(data_dict)

async def subscribe_to_channel(avanza: Avanza):
    await avanza.subscribe_to_id(
        ChannelType.QUOTES,
        "19002", # OMX Stockholm 30
        callback
    )

def main(user):
    avanza = Avanza({
        'username': keyring.get_password(user, 'un'),
        'password': keyring.get_password(user, 'pass'),
        'totpSecret': keyring.get_password(user, 'totp')})

    asyncio.get_event_loop().run_until_complete(
        subscribe_to_channel(avanza)
    )
    asyncio.get_event_loop().run_forever()

if __name__ == "__main__":
    main('ava_elbe')
"""


import yfinance as yf

ticker_obj = yf.Ticker("^OMX")
history_df = ticker_obj.history(period="1day", interval="1m")

print(history_df)
