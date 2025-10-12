def fixed_fraction_sizer(capital, fraction=0.04, price_per_spread=200.0):
    alloc = max(0.0, capital * fraction)
    n = int(alloc // price_per_spread)
    return n, n * price_per_spread

def fractional_kelly(mean_ret, std_ret, kelly_cap=0.25):
    if std_ret <= 0:
        return 0.0
    k = (mean_ret / (std_ret**2))
    return float(max(0.0, min(k, kelly_cap)))
