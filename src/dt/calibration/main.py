import logging
import traceback

from src.utils import Context, Settings, TeleLog

log = logging.getLogger("main.dt.calibration")


class Calibration:
    def __init__(self):
        self.settings = Settings().load("DT")

        self.ava = Context(
            self.settings["user"], self.settings["accounts"], process_lists=False
        )

        self.tickers = {}

        self.recalculate_stocks_weights()

    def recalculate_stocks_weights(self) -> None:
        """
        Calculate stocks weights based on market capitalization and compare to OMX weights.
        OMX30 reference weights: https://www.nasdaq.com/docs/2023/05/03/OMXS30.pdf

        Args:
            omx_weights (dict): dict with ticker symbols and their reference weights
        """

        log.info("Recalculate stocks weights")

        normalization_factor = {
            "AZN.ST": 7.5,
            "NDA-SE.ST": 2,
        }

        # Find tickers on Avanza
        for ticker_yahoo, weight in self.settings["omx_weights"].items():
            stock = self.ava.ctx.find_stock_data(
                ticker_yahoo.replace("-", " ").replace(".ST", "")
            )

            stock_info: dict = self.ava.ctx.get_stock_info(stock["id"])  # type: ignore

            self.tickers[ticker_yahoo] = {
                "weight_nasdaq": weight["nasdaq"],
                "orderbook_id": stock_info["orderbookId"],
                "ticker_yahoo": ticker_yahoo,
                "market_cap_calc": round(
                    stock_info["stock"]["numberOfShares"]
                    * stock_info["quote"]["last"]
                    / normalization_factor.get(ticker_yahoo, 1)
                ),
            }

            self.settings["omx_weights"][ticker_yahoo]["orderbook_id"] = stock_info[
                "orderbookId"
            ]

        # Calculate weights
        total_market_valuation = sum(
            [i["market_cap_calc"] for i in self.tickers.values()]
        )

        for ticker in self.tickers.values():
            ticker["weight_calc"] = round(
                (ticker["market_cap_calc"] / total_market_valuation) * 100, 2
            )

        # Filter tickers to keep the most impactful ones
        filtered_tickers = {}
        for ticker_yahoo, ticker in self.tickers.items():
            self.settings["omx_weights"][ticker_yahoo]["weight_calc"] = ticker[
                "weight_calc"
            ]

            if (
                abs(ticker["weight_calc"] - ticker["weight_nasdaq"])
                / ticker["weight_calc"]
                * 100
                > 20
            ):
                log.warning(
                    f"> {ticker_yahoo}: Too high discrepancy {ticker['weight_nasdaq']}% (NASDAQ) vs {ticker['weight_calc']}% (mine)"
                )

            if ticker["weight_calc"] < 2.5:
                log.warning(
                    f"> {ticker_yahoo}: Too low impact {ticker['weight_calc']}%"
                )

                self.settings["omx_weights"][ticker_yahoo]["skip"] = True

            else:
                filtered_tickers[ticker_yahoo] = ticker

        log.info(
            f"> {len(filtered_tickers)} stocks provide {round(sum([i['weight_calc'] for i in filtered_tickers.values()]))}% impact"
        )

        # Save recalculated weights to settings
        Settings().dump(self.settings, "DT")

        if self.settings["log_to_telegram"]:
            TeleLog(message="DT Calibration: Done")


def run() -> None:
    try:
        Calibration()

    except Exception as e:
        log.error(f">>> {e}: {traceback.format_exc()}")

        TeleLog(crash_report=f"DT calibration: script has crashed: {e}")
