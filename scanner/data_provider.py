"""Select the configured read-only market-data/account connector."""

import config

if config.MARKET_DATA_PROVIDER == "BIQUOTE":
    from scanner.mt5_connector import connect, disconnect, get_account_info, get_bars, get_symbol_info
elif config.MARKET_DATA_PROVIDER == "DERIV_DEMO":
    from scanner.deriv_connector import connect, disconnect, get_account_info, get_bars, get_symbol_info
else:
    raise ValueError(
        "MARKET_DATA_PROVIDER must be BIQUOTE or DERIV_DEMO."
    )