import logging
from dataclasses import dataclass, field
from typing import Optional

from avanza import OrderType

from module.dt.common_types import Instrument

log = logging.getLogger("main.dt.trading.status")


@dataclass
class InstrumentStatus:
    instrument: Instrument
    stop_settings: dict

    price_sell: Optional[float] = None
    price_buy: Optional[float] = None
    spread: Optional[float] = None

    position: dict = field(default_factory=dict)
    active_order: dict = field(default_factory=dict)
    last_sell_deal: dict = field(default_factory=dict)

    acquired_price: Optional[float] = None

    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    price_max: Optional[float] = None

    def extract(self, instrument_info: dict) -> None:
        self.position = instrument_info["position"]
        self.last_sell_deal = (
            instrument_info["last_deal"]
            if instrument_info["last_deal"].get("orderType") == "SELL"
            else {}
        )

        if (
            self.acquired_price
            and self.last_sell_deal.get("price")
            and not self.position
        ):
            log.warning(
                ", ".join(
                    [
                        f'{self.instrument.value} ===> Verdict: {"good" if self.acquired_price < self.last_sell_deal["price"] else "bad"}',
                        f"Acquired: {self.acquired_price}",
                        f"Sold: {self.last_sell_deal['price']}",
                        f"Profit: {round((self.last_sell_deal['price'] / self.acquired_price - 1)* 100, 2)}%",
                    ]
                )
            )

            self.price_max = None
            self.acquired_price = None

        elif not self.acquired_price and self.position:
            self.acquired_price = self.position["acquiredPrice"]

        self.spread = instrument_info["spread"]
        self.active_order = instrument_info["order"]

        if self.price_max and self.price_sell:
            self.price_max = max(self.price_max, self.price_sell)

        elif not self.price_max:
            self.price_max = self.price_sell

        if self.spread and self.spread >= self.stop_settings["spread_limit"]:
            self.price_buy = None
            self.price_sell = None

            log.debug(f"{self.instrument.value} ===> High spread: {self.spread}")

        else:
            self.price_buy = instrument_info[OrderType.BUY]
            self.price_sell = instrument_info[OrderType.SELL]

    def update_limits(self, atr) -> None:
        if not self.position or self.price_sell is None:
            return None

        self.stop_loss = round(
            self.acquired_price * (1 - (1 - self.stop_settings["stop_loss"]) * atr), 2
        )
        self.take_profit = round(
            self.acquired_price * (1 + (self.stop_settings["take_profit"] - 1) * atr), 2
        )

    def get_profit(self) -> float:
        return (
            0.0
            if (
                not self.position
                or not self.acquired_price
                or not self.price_sell
                or round(self.price_sell - self.acquired_price, 2) == 0
            )
            else round(
                ((self.price_sell - self.acquired_price) / self.acquired_price) * 100, 2
            )
        )
