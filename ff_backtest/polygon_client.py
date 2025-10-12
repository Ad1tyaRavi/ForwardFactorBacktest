import os
import time
from typing import Dict, Any, Optional
import requests
from dotenv import load_dotenv

# Load .env automatically
load_dotenv()

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")

class PolygonClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key or POLYGON_API_KEY
        if not self.api_key:
            raise ValueError("Set POLYGON_API_KEY in .env or pass api_key.")
        self.base_url = base_url
        self.session = requests.Session()

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params or {})
        params["apiKey"] = self.api_key
        url = f"{self.base_url}{path}"
        while True:
            r = self.session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "1"))
                time.sleep(max(1.0, wait))
                continue
            r.raise_for_status()
            return r.json()

    def snapshot_option_chain(self, underlying: str):
        return self._get(f"/v3/snapshot/options/{underlying}", {})

    def previous_close(self, ticker: str) -> Optional[float]:
        data = self._get(f"/v2/aggs/ticker/{ticker}/prev", {})
        results = data.get("results", [])
        if not results:
            return None
        return float(results[0].get("c"))
