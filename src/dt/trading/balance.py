import logging
from dataclasses import dataclass

log = logging.getLogger("main.dt.trading.balance")


@dataclass
class Balance:
    before: float
    tradable: float
    daily_target: float
    daily_limit: float

    not_tradable: float = 0

    after: float = 0

    def __post_init__(self) -> None:
        self.not_tradable = round(self.before - self.tradable)

        self.daily_target *= self.tradable
        self.daily_limit *= self.tradable

        log.info(f"Balance before: {round(self.before)}")
        log.info(f"Trading budget: {round(self.tradable)}")

    def update_after(self, total_balance: float) -> None:
        self.after = total_balance

        log.info(f"Balance after: {round(self.after)}")

    def summarize(self) -> dict:
        return {
            "balance_before": self.before,
            "balance_after": self.after,
            "budget": self.tradable,
        }
