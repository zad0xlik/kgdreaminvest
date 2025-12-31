"""Greeks calculation utilities using Black-Scholes model."""
import math
from datetime import datetime
from typing import Optional

import numpy as np
from scipy.stats import norm


def calculate_dte(expiration_str: str) -> int:
    """
    Calculate days to expiration from expiration string.
    
    Args:
        expiration_str: Date string in format 'YYYY-MM-DD'
        
    Returns:
        Days to expiration (integer)
    """
    try:
        exp_date = datetime.strptime(expiration_str, "%Y-%m-%d")
        today = datetime.now()
        dte = (exp_date - today).days
        return max(0, dte)
    except Exception:
        return 0


def calculate_greeks(
    spot: float,
    strike: float,
    dte: int,
    risk_free_rate: float,
    implied_vol: float,
    option_type: str
) -> dict:
    """
    Calculate option Greeks using Black-Scholes model.
    
    Args:
        spot: Current price of underlying
        strike: Strike price of option
        dte: Days to expiration
        risk_free_rate: Risk-free interest rate (annual, e.g., 0.05 for 5%)
        implied_vol: Implied volatility (e.g., 0.25 for 25%)
        option_type: 'Call' or 'Put'
        
    Returns:
        Dict with keys: delta, gamma, theta, vega, rho
    """
    if dte <= 0 or spot <= 0 or strike <= 0 or implied_vol <= 0:
        return {
            "delta": 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0
        }
    
    # Convert days to years
    T = dte / 365.0
    
    # Black-Scholes d1 and d2
    d1 = (np.log(spot / strike) + (risk_free_rate + 0.5 * implied_vol ** 2) * T) / (implied_vol * np.sqrt(T))
    d2 = d1 - implied_vol * np.sqrt(T)
    
    # Calculate Greeks
    if option_type.upper() == 'CALL':
        delta = norm.cdf(d1)
        theta = ((-spot * norm.pdf(d1) * implied_vol) / (2 * np.sqrt(T)) 
                 - risk_free_rate * strike * np.exp(-risk_free_rate * T) * norm.cdf(d2)) / 365.0
        rho = strike * T * np.exp(-risk_free_rate * T) * norm.cdf(d2) / 100.0
    else:  # PUT
        delta = norm.cdf(d1) - 1
        theta = ((-spot * norm.pdf(d1) * implied_vol) / (2 * np.sqrt(T)) 
                 + risk_free_rate * strike * np.exp(-risk_free_rate * T) * norm.cdf(-d2)) / 365.0
        rho = -strike * T * np.exp(-risk_free_rate * T) * norm.cdf(-d2) / 100.0
    
    # Gamma and Vega are same for calls and puts
    gamma = norm.pdf(d1) / (spot * implied_vol * np.sqrt(T))
    vega = spot * norm.pdf(d1) * np.sqrt(T) / 100.0  # Divide by 100 for 1% change
    
    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
        "rho": float(rho)
    }


def enrich_option_with_greeks(
    option_row: dict,
    spot_price: float,
    risk_free_rate: float = 0.045
) -> dict:
    """
    Enrich an option data row with calculated Greeks.
    
    Args:
        option_row: Dict with option data (must have strike, expiration, impliedVolatility, optionType)
        spot_price: Current price of underlying
        risk_free_rate: Annual risk-free rate (default ~4.5%)
        
    Returns:
        Dict with original data plus calculated Greeks
    """
    try:
        strike = float(option_row.get("strike", 0))
        expiration = str(option_row.get("Expiration", ""))
        iv = float(option_row.get("impliedVolatility", 0))
        option_type = str(option_row.get("OptionType", "Call"))
        
        dte = calculate_dte(expiration)
        
        greeks = calculate_greeks(
            spot=spot_price,
            strike=strike,
            dte=dte,
            risk_free_rate=risk_free_rate,
            implied_vol=iv,
            option_type=option_type
        )
        
        # Merge Greeks into option row
        enriched = dict(option_row)
        enriched.update(greeks)
        enriched["dte"] = dte
        
        return enriched
        
    except Exception as e:
        # Return original row with zero Greeks on error
        return {
            **option_row,
            "delta": 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
            "dte": 0
        }
