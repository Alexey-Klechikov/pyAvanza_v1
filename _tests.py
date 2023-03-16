import pandas as pd
from pprint import pprint

data = pd.read_pickle("module/cache/^OMX.pickle")


gap_limit = 5


# gap between days
# gaps = {}
# day_close = None
# for date, group_date in data.groupby(data.index.date):
#     if day_close is not None:
#         gaps[date] = group_date.iloc[0]["Open"] - day_close
#         gaps[date] = gaps[date] if abs(gaps[date]) > gap_limit else None

#     day_close = group_date.iloc[-1]["Close"]

# first 5 minutes
gaps = {}
for date, group_date in data.groupby(data.index.date):
    gaps[date] = group_date.iloc[5]["Close"] - group_date.iloc[0]["Open"]
    gaps[date] = gaps[date] if abs(gaps[date]) > gap_limit else None


counters = {}
for date, group_date in data.groupby(data.index.date):
    gap = gaps.get(date)
    if not gap:
        continue

    for interval, group in group_date.groupby(pd.Grouper(freq="5min")):
        time = interval.time().strftime("%H:%M")
        counters.setdefault(
            time,
            {
                "time": f'{group.iloc[0].name.time().strftime("%H:%M")}-{group.iloc[-1].name.time().strftime("%H:%M")}',
                "correlated": 0,
                "total": 0,
                "all_interval_gaps": [],
                "correlated_interval_gaps": [],
            },
        )

        if group.empty:
            continue

        interval_gap = group.iloc[-1]["Close"] - group.iloc[0]["Open"]

        if gap * interval_gap > 0:
            counters[time]["correlated"] += 1
            counters[time]["correlated_interval_gaps"].append(interval_gap)

        counters[time]["all_interval_gaps"].append(interval_gap)
        counters[time]["total"] += 1

for time, counter in counters.items():
    correlation_percentage = round(counter["correlated"] / counter["total"] * 100, 2)
    average_all_interval_gap = round(
        sum(counter["all_interval_gaps"]) / len(counter["all_interval_gaps"]), 2
    )
    average_correlated_interval_gaps = (
        0
        if len(counter["correlated_interval_gaps"]) == 0
        else round(
            sum(counter["correlated_interval_gaps"])
            / len(counter["correlated_interval_gaps"]),
            2,
        )
    )

    print(
        counter["time"],
        correlation_percentage,
        average_correlated_interval_gaps,
        "---",
        average_all_interval_gap,
        " * " if correlation_percentage > 60 or correlation_percentage < 40 else "",
    )
