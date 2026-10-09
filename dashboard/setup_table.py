import pandas as pd


ACTIVE_SETUP_COLUMNS = [
    "detected_at",
    "symbol",
    "signal_type",
    "timeframe",
    "bias",
    "grade",
    "score",
    "entry",
    "sl",
    "tp1",
    "session",
]


def build_active_setups_table(setups):
    dataframe = pd.DataFrame(setups)
    if "signal_type" not in dataframe.columns:
        dataframe["signal_type"] = "Not recorded"
    else:
        dataframe["signal_type"] = dataframe["signal_type"].fillna("Not recorded")

    columns = [column for column in ACTIVE_SETUP_COLUMNS if column in dataframe.columns]
    return dataframe[columns].reset_index(drop=True)