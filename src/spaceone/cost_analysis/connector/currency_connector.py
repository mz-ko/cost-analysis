import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import FinanceDataReader as fdr
from typing import Tuple, Union

from spaceone.core import config
from spaceone.core.connector import BaseConnector

__all__ = ["CurrencyConnector"]

_LOGGER = logging.getLogger(__name__)


class CurrencyConnector(BaseConnector):
    from_exchange_currencies = config.get_global(
        "SUPPORTED_CURRENCIES", ["KRW", "USD", "JPY"]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def add_currency_map_date(
        self, currency_end_date: datetime, currency_start_date: datetime = None
    ) -> Tuple[dict, datetime]:
        currency_map = self._initialize_currency_map()
        currency_date = currency_end_date

        for from_currency in self.from_exchange_currencies:
            for to_currency in self.from_exchange_currencies:
                if from_currency == to_currency:
                    exchange_rate = 1.0
                else:
                    pair = f"{from_currency}/{to_currency}"
                    exchange_rate_info = self._get_exchange_rate_info(
                        pair=pair,
                        currency_end_date=currency_end_date,
                        currency_start_date=currency_start_date,
                    )

                    currency_date, exchange_rate = exchange_rate_info.iloc[-1]
                currency_map[from_currency][
                    f"{from_currency}/{to_currency}"
                ] = exchange_rate

        _LOGGER.debug(
            f"[add_currency_map_date] get currency_map successfully for {currency_date}"
        )
        return currency_map, currency_date

    def _initialize_currency_map(self):
        currency_map = {}
        for exchange_currency in self.from_exchange_currencies:
            currency_map[exchange_currency] = {}
        return currency_map

    @staticmethod
    def http_datareader(pair, currency_end_date, currency_start_date) -> dict:
        pair = f"{pair.replace('/','')}=X"
        start_date_time_stamp = int(currency_start_date.timestamp())
        end_date_time_stamp = int(currency_end_date.timestamp())

        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{pair}?period1={start_date_time_stamp}&period2={end_date_time_stamp}&interval=1d&events=history&includeAdjustedClose=true"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        response = requests.request(method="GET", url=url, headers=headers, timeout=3)
        return response.json()

    def _get_exchange_rate_info(
        self,
        pair: str,
        currency_end_date: datetime,
        currency_start_date: Union[datetime, None] = None,
    ):
        df = None

        try:
            currency_end_date = currency_end_date.replace(
                hour=23, minute=59, second=59, microsecond=59
            )

            if not currency_start_date:
                currency_start_date = currency_end_date - relativedelta(days=15)
            df = (
                fdr.DataReader(pair, start=currency_start_date, end=currency_end_date)
                .dropna()
                .reset_index(names="Date")[["Date", "Close"]]
            )
            return df
        except Exception as e:
            _LOGGER.warning(f"[get_exchange_rate_info] Failed {e}, {df} => trying Yahoo Finance API")
            try:
                response_json = self.http_datareader(
                    pair, currency_end_date, currency_start_date
                )

                quotes = response_json["chart"]["result"][0]["indicators"]["quote"][0]
                timestamps = response_json["chart"]["result"][0]["timestamp"]

                # convert bst to utc
                converted_datetime = [
                    datetime.fromtimestamp(ts, tz=timezone.utc) for ts in timestamps
                ]

                df = pd.DataFrame(
                    {
                        "Date": converted_datetime,
                        "Close": quotes["close"],
                    }
                )

                return df.dropna().reset_index()[["Date", "Close"]]
            except Exception as e2:
                _LOGGER.warning(f"[get_exchange_rate_info] Error while fetching data from Yahoo Finance API. {e2}")
                _LOGGER.warning(f"[get_exchange_rate_info] Returning default rate_info DataFrame from global config.")

                default_rates = config.get_global("DEFAULT_EXCHANGE_RATES", {})
                dates = self.make_datetime_list(currency_start_date, currency_end_date)
                rates = self.make_default_rates_list(pair, default_rates, len(dates))

                df = pd.DataFrame({
                    "Date": dates,
                    "Close": rates
                })

                return df.dropna().reset_index()[["Date", "Close"]]

    @staticmethod
    def make_datetime_list(start_date: datetime, end_date: datetime) -> list[datetime]:
        dates = []
        while start_date <= end_date:
            dates.append(start_date)
            start_date += relativedelta(days=1)
        return dates

    @staticmethod
    def make_default_rates_list(pair: str, default_rates: dict, count: int) -> list[float]:
        if default_rates and default_rates.get(pair):
            try:
                rate = float(default_rates[pair])
                return [rate] * count
            except ValueError as e:
                _LOGGER.error(f"[make_default_rates_list] Invalid rate value for pair {pair}: {default_rates[pair]}. Error: {e}")
                raise ValueError(f"Invalid rate value for pair {pair}: {default_rates[pair]}")
        else:
            _LOGGER.error(f"[make_default_rates_list] Pair {pair} not found in default rates.")
            raise ValueError(f"Pair {pair} not found in default rates: {default_rates}")

