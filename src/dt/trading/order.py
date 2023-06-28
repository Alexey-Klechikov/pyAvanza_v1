import logging
from typing import Optional

from avanza import OrderType

from src.dt import Instrument
from src.utils import Context

log = logging.getLogger("main.dt.trading.order")


class Order:
    def __init__(self, ava: Context, settings: dict):
        self.ava = ava
        self.settings = settings

    def place(
        self,
        signal: OrderType,
        market_direction: Instrument,
        instrument_status: dict,
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
            and instrument_status[signal]
            and not instrument_status["position"]
        ):
            order_data.update(
                {
                    "price": instrument_status[signal],
                    "volume": int(
                        self.settings["trading"]["budget"] // instrument_status[signal]
                    ),
                    "budget": self.settings["trading"]["budget"],
                }
            )

        elif (
            signal == OrderType.SELL
            and instrument_status[signal]
            and instrument_status["position"]
        ):
            order_data.update(
                {
                    "price": instrument_status[signal],
                    "volume": instrument_status["position"]["volume"],
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
        instrument_status: dict,
        custom_price: Optional[float] = None,
    ) -> None:
        price = None

        if custom_price:
            price = custom_price

        elif signal == OrderType.BUY and instrument_status[signal]:
            price = instrument_status[signal]

        elif signal == OrderType.SELL and instrument_status[signal]:
            price = instrument_status[signal]

        if not price or not instrument_status["spread"]:
            return

        log.debug(
            f'{market_direction} - (UPD {signal.name.upper()} order): {instrument_status["order"]["price"]} -> {price} '
        )

        self.ava.update_order(
            instrument_status["order"],
            price,
            self.settings["instruments"]["TRADING"][market_direction][1],
            self.settings["instruments"]["TRADING"][market_direction][0],
        )

    def delete(self) -> None:
        self.ava.delete_active_orders(account_ids=[self.settings["accounts"]["DT"]])
