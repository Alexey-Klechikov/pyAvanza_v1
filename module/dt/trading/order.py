import logging
from typing import Optional

from avanza import OrderType

from module.dt.common_types import Instrument
from module.dt.trading.status import InstrumentStatus
from module.utils import Context

log = logging.getLogger("main.dt.trading.order")


class Order:
    def __init__(self, ava: Context, settings: dict):
        self.ava = ava
        self.settings = settings

    def place(
        self,
        signal: OrderType,
        market_direction: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        order_data = {
            "name": market_direction,
            "signal": signal,
            "account_id": list(self.settings["accounts"].values())[0],
            "order_book_id": self.settings["instruments"]["TRADING"][market_direction][
                1
            ],
        }

        if (
            signal == OrderType.BUY
            and instrument_status.price_buy
            and not instrument_status.position
        ):
            order_data.update(
                {
                    "price": instrument_status.price_buy,
                    "volume": int(
                        self.settings["trading"]["budget"]
                        // instrument_status.price_buy
                    ),
                    "budget": self.settings["trading"]["budget"],
                }
            )

        elif (
            signal == OrderType.SELL
            and instrument_status.price_sell
            and instrument_status.position
        ):
            order_data.update(
                {
                    "price": instrument_status.price_sell,
                    "volume": instrument_status.position["volume"],
                }
            )

        else:
            return

        if custom_price:
            order_data["price"] = custom_price

        self.ava.create_orders(
            [order_data],
            signal,
        )

        log.debug(
            f'{market_direction} - (SET {signal.name.upper()} order): {order_data["price"]} for {self.settings["instruments"]["TRADING"][market_direction]}'
        )

    def update(
        self,
        signal: OrderType,
        market_direction: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        price = None

        if custom_price:
            price = custom_price

        elif signal == OrderType.BUY and instrument_status.price_buy:
            price = instrument_status.price_buy

        elif signal == OrderType.SELL and instrument_status.price_sell:
            price = instrument_status.price_sell

        if not price or not instrument_status.spread:
            return

        log.debug(
            f'{market_direction} - (UPD {signal.name.upper()} order): {instrument_status.active_order["price"]} -> {price} '
        )

        self.ava.update_order(
            instrument_status.active_order,
            price,
            self.settings["instruments"]["TRADING"][market_direction][1],
            self.settings["instruments"]["TRADING"][market_direction][0],
        )

    def delete(self) -> None:
        self.ava.delete_active_orders(account_ids=[self.settings["accounts"]["DT"]])
