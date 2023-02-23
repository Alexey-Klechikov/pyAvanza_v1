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
        self.last_sell_deal = (
            instrument_info["last_deal"]
            if instrument_info["last_deal"].get("orderType") == "SELL"
            else {}
        )

        self.position = instrument_info["position"]

        if self.position:
            self.acquired_price = self.position.get("acquiredPrice")

        elif self.acquired_price:
            price_sell = self.last_sell_deal.get(
                "price", self.price_sell if self.price_sell else 0
            )

            log.warning(
                ", ".join(
                    [
                        f'{self.instrument.value} ===> Verdict: {"good" if self.acquired_price < price_sell else "bad"}',
                        f"Acquired: {self.acquired_price}",
                        f"Sold: {price_sell}",
                        f"Profit: {round((price_sell / self.acquired_price - 1)* 100, 2)}%",
                    ]
                )
            )

            self.price_max = None
            self.acquired_price = None

        self.spread = instrument_info["spread"]
        self.active_order = instrument_info["order"]

        if self.acquired_price:
            self.price_max = max(
                self.price_max if self.price_max else self.acquired_price,
                self.price_sell if self.price_sell else self.acquired_price,
            )

        if (
            self.spread
            and self.spread >= self.stop_settings["spread_limit"]
            and not instrument_info["is_deprecated"]
        ):
            self.price_buy = None
            self.price_sell = None

            log.debug(f"{self.instrument.value} ===> High spread: {self.spread}")

        else:
            self.price_buy = instrument_info[OrderType.BUY]
            self.price_sell = instrument_info[OrderType.SELL]

    def update_limits(self, atr: float) -> None:
        if not self.position or self.price_sell is None:
            return None

        self.stop_loss = round(
            self.price_sell * (1 - (1 - self.stop_settings["stop_loss"]) * atr), 2
        )
        self.take_profit = round(
            self.price_sell * (1 + (self.stop_settings["take_profit"] - 1) * atr), 2
        )

    def get_profit(self) -> float:
        return (
            0.0
            if (not self.position or not self.acquired_price or not self.price_sell)
            else round((self.price_sell / self.acquired_price - 1) * 100, 2)
        )
