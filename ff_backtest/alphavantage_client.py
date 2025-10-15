import os
import time
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

# Automatically load variables from a local .env file so the script works out of
# the box after following the setup instructions.
load_dotenv()


ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")


class AlphaVantageClient:
    """Thin wrapper around the AlphaVantage REST API used by the fetcher."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://www.alphavantage.co/query",
        max_per_minute: int = 5,
    ) -> None:
        self.api_key = api_key or ALPHAVANTAGE_API_KEY
        if not self.api_key:
            raise ValueError("Set ALPHAVANTAGE_API_KEY in .env or pass api_key.")
        self.base_url = base_url
        self.max_per_minute = max_per_minute
        self._window_start = time.time()
        self._calls_in_window = 0
        self.session = requests.Session()

    def _throttle(self) -> None:
        if self.max_per_minute <= 0:
            return
        now = time.time()
        elapsed = now - self._window_start
        if elapsed >= 60:
            self._window_start = now
            self._calls_in_window = 0
            elapsed = 0
        if self._calls_in_window >= self.max_per_minute:
            sleep_for = max(0.0, 60 - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._window_start = time.time()
            self._calls_in_window = 0

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params or {})
        params["apikey"] = self.api_key

        while True:
            self._throttle()
            resp = self.session.get(self.base_url, params=params, timeout=30)
            self._calls_in_window += 1
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and any(
                key in data for key in ("Note", "Information", "Error Message")
            ):
                # When the API returns a "Note" the key limit has been hit. Back
                # off for a minute before retrying.
                time.sleep(60)
                continue
            return data

    def option_chain(self, symbol: str) -> Dict[str, Any]:
        return self._get({"function": "OPTIONS", "symbol": symbol})

    def global_quote(self, symbol: str) -> Dict[str, Any]:
        return self._get({"function": "GLOBAL_QUOTE", "symbol": symbol})

