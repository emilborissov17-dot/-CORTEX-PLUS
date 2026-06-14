
def _wb_latest(indicator: str) -> Optional[float]:
    try:
        url = f"{WB_API}/indicator/{indicator}/latest"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and len(data) > 1:
            return float(data[1][1])
        return None
    except Exception as e:
        print(f"Error fetching {indicator}: {e}")
        return None
