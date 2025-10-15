import os
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union

from alpha_vantage.options import Options
from alpha_vantage.timeseries import TimeSeries
from dotenv import load_dotenv

# Automatically load variables from a local .env file so the script works out of
# the box after following the setup instructions.
load_dotenv()


ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")


JsonLike = Union[Dict[str, Any], Tuple[Any, ...]]


class AlphaVantageClient:
    """Wrapper that reuses the official alpha_vantage package."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_per_minute: int = 5,
    ) -> None:
        self.api_key = api_key or ALPHAVANTAGE_API_KEY
        if not self.api_key:
            raise ValueError("Set ALPHAVANTAGE_API_KEY in .env or pass api_key.")
        self.max_per_minute = max_per_minute
        self._window_start = time.time()
        self._calls_in_window = 0

        # The alpha_vantage package automatically builds the request URLs. Using
        # JSON keeps the existing fetcher logic intact.
        self._options = Options(
            key=self.api_key,
            output_format="json",
            treat_info_as_error=True,
        )
        self._timeseries = TimeSeries(
            key=self.api_key,
            output_format="json",
            treat_info_as_error=True,
        )

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

    def _execute(self, func: Callable[..., JsonLike], *args: Any, **kwargs: Any) -> Dict[str, Any]:
        while True:
            self._throttle()
            try:
                result = func(*args, **kwargs)
            except ValueError as exc:
                # When the rate limit is exceeded the wrapper raises ValueError
                # with the original "Note" message. Sleep and retry so callers
                # do not have to handle it themselves.
                msg = str(exc)
                if "Thank you for using Alpha Vantage" in msg or "frequency" in msg.lower():
                    time.sleep(60)
                    self._window_start = time.time()
                    self._calls_in_window = 0
                    continue
                raise

            self._calls_in_window += 1

            payload: Any
            if isinstance(result, tuple) and result:
                payload = result[0]
            else:
                payload = result

            if isinstance(payload, dict) and any(
                key in payload for key in ("Note", "Information", "Error Message")
            ):
                time.sleep(60)
                self._window_start = time.time()
                self._calls_in_window = 0
                continue

            if not isinstance(payload, dict):
                raise TypeError(
                    "Expected alpha_vantage response to be a dict, got "
                    f"{type(payload).__name__}"
                )

            return payload

    def option_chain(self, symbol: str) -> Dict[str, Any]:
        return self._execute(self._options.get_option_chain, symbol=symbol)

    def global_quote(self, symbol: str) -> Dict[str, Any]:
        return self._execute(self._timeseries.get_quote_endpoint, symbol=symbol)

