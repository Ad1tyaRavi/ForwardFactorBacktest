import numpy as np

def annualized_days(days: float) -> float:
    return days / 365.0

def forward_variance(sig1: float, sig2: float, T1_years: float, T2_years: float) -> float:
    if T2_years <= T1_years:
        return np.nan
    v1, v2 = sig1**2, sig2**2
    return (T2_years * v2 - T1_years * v1) / (T2_years - T1_years)

def forward_vol(sig1: float, sig2: float, T1_years: float, T2_years: float) -> float:
    fv = forward_variance(sig1, sig2, T1_years, T2_years)
    if fv <= 0 or np.isnan(fv):
        return np.nan
    return float(np.sqrt(fv))

def forward_factor(sig_front: float, sig_fwd: float) -> float:
    if sig_fwd <= 0 or np.isnan(sig_fwd) or sig_front <= 0:
        return np.nan
    return (sig_fwd - sig_front) / sig_front
