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
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        if (
            (signal == OrderType.BUY and instrument_status.position)
            or (signal == OrderType.SELL and not instrument_status.position)
            or instrument_status.price_buy is None
            or instrument_status.price_sell is None
        ):
            return

        order_data = {
            "name": instrument_type,
            "signal": signal,
            "account_id": list(self.settings["accounts"].values())[0],
            "order_book_id": self.settings["instruments"]["TRADING"][instrument_type],
        }

        if signal == OrderType.BUY:
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

        elif signal == OrderType.SELL:
            order_data.update(
                {
                    "price": instrument_status.price_sell,
                    "volume": instrument_status.position["volume"],
                }
            )

        if custom_price is not None:
            order_data["price"] = custom_price

        self.ava.create_orders(
            [order_data],
            signal,
        )

        log.debug(
            f'{instrument_type} - (SET {signal.name.upper()} order): {order_data["price"]} for {self.settings["instruments"]["TRADING"][instrument_type]}'
        )

    def update(
        self,
        signal: OrderType,
        instrument_type: Instrument,
        instrument_status: InstrumentStatus,
        custom_price: Optional[float] = None,
    ) -> None:
        if (
            instrument_status.price_buy is None
            or instrument_status.price_sell is None
            or instrument_status.spread is None
        ):
            return

        price = (
            instrument_status.price_buy
            if signal == OrderType.BUY
            else instrument_status.price_sell
        )

        if custom_price is not None:
            price = custom_price

        log.debug(
            f'{instrument_type} - (UPD {signal.name.upper()} order): {instrument_status.active_order["price"]} -> {price} '
        )

        self.ava.update_order(
            instrument_status.active_order,
            price,
            self.settings["instruments"]["TRADING"][instrument_type],
            "WARRANT",
        )

    def delete(self) -> None:
        self.ava.delete_active_orders(account_ids=[self.settings["accounts"]["DT"]])
