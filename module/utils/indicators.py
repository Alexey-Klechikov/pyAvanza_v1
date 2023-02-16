import numpy as np
import pandas as pd
import pandas_ta as ta


class CustomIndicators:

    # Volume
    @staticmethod
    def volume_flow(
        data: pd.DataFrame,
        period: int,
        smooth: int,
        ma_period: int,
        coef: float,
        vol_coef: float,
    ) -> pd.DataFrame:
        """https://precisiontradingsystems.com/volume-flow.htm"""

        make_name = lambda x: f"{x}_{period}_{smooth}_{ma_period}_{coef}_{vol_coef}"

        data["_inter"] = np.log(data["Close"]).diff()  # type: ignore
        data["_vinter"] = ta.stdev(data["_inter"], length=30)
        data["_cutoff"] = coef * data["_vinter"] * data["Close"]
        data["_vave"] = ta.sma(data["Volume"], length=period).shift(1)  # type: ignore
        data["_vmax"] = data["_vave"] * vol_coef
        data["_mf"] = data["Close"] - data["Close"].shift(1)
        data["_vcp"] = np.where(
            data["_mf"] > data["_cutoff"],
            data["Volume"].clip(upper=data["_vmax"]),
            np.where(
                data["_mf"] < -data["_cutoff"],
                -data["Volume"].clip(upper=data["_vmax"]),
                0,
            ),
        )
        data[make_name("VFI")] = ta.ema(
            ta.sma(data["_vcp"], length=period) / data["_vave"], length=smooth  # type: ignore
        )
        data[make_name("VFI_MA")] = ta.sma(
            ta.ema(
                ta.sma(data["_vcp"], length=period) / data["_vave"], length=smooth  # type: ignore
            ),
            length=ma_period,
        )

        return data

    # Trend
    @staticmethod
    def trend_intensity(
        data: pd.DataFrame, length_sma: int, length_signal: int
    ) -> pd.DataFrame:
        """https://raposa.trade/blog/4-ways-to-trade-the-trend-intensity-indicator/"""

        make_name = lambda x: f"{x}_{length_sma}_{length_signal}"

        sma = data.ta.sma(length=length_sma)
        diff = data["Close"] - sma
        pos_count = (
            diff.map(lambda x: 1 if x > 0 else 0).rolling(int(length_sma / 2)).sum()
        )
        data[make_name("TII")] = 200 * (pos_count) / length_sma
        data[make_name("TII_SIGNAL")] = data.ta.ema(
            close=data[make_name("TII")], length=length_signal
        )

        return data

    # Volatility
    @staticmethod
    def starc_bands(
        data: pd.DataFrame, length_sma: int, length_atr: int, multiplier_atr: float
    ):
        """https://www.investopedia.com/terms/s/starc.asp"""

        make_name = lambda x: f"{x}_{length_sma}_{length_atr}_{multiplier_atr}"

        sma = data.ta.sma(length=length_sma)
        atr = data.ta.atr(length=length_atr)

        data[make_name("STARC_U")] = sma + multiplier_atr * atr
        data[make_name("STARC_B")] = sma - multiplier_atr * atr

        return data

    # Momentum
    @staticmethod
    def impulse_macd(
        data: pd.DataFrame, length_ma: int, length_signal: int
    ) -> pd.DataFrame:
        """https://www.tradingview.com/script/qt6xLfLi-Impulse-MACD-LazyBear/"""

        make_name = lambda x: f"{x}_{length_ma}_{length_signal}"

        def _smooth_simple_moving_average(src, length):
            ssma = np.full(len(src), np.nan)
            ssma[0] = src[:length].mean()

            for i in range(1, len(src)):
                ssma[i] = (ssma[i - 1] * (length - 1) + src[i]) / length

            return ssma

        def _zero_lag_exponential_moving_average(src, length):
            ema1 = pd.Series(src).ewm(span=length).mean()
            ema2 = ema1.ewm(span=length).mean()
            d = ema1 - ema2

            return ema1 + d

        high_smooth = _smooth_simple_moving_average(data["High"], length_ma)
        low_smooth = _smooth_simple_moving_average(data["Low"], length_ma)

        mean_price = data[["High", "Low", "Close"]].mean(axis=1)
        mean_zlema = _zero_lag_exponential_moving_average(mean_price, length_ma)

        data[make_name("IMPULSE")] = np.where(
            mean_zlema > high_smooth,
            mean_zlema - high_smooth,
            np.where(mean_zlema < low_smooth, mean_zlema - low_smooth, 0),
        )

        data[make_name("SIGNAL")] = (
            pd.Series(data[make_name("IMPULSE")]).rolling(length_signal).mean()
        )

        return data
