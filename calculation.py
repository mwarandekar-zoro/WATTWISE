"""
Phase 3, 4, 6 & 9: Calculation engine, WattWise Energy Score, appliance
breakdown, and savings simulator.

Everything here is plain Python arithmetic. No LLM involvement --
these numbers need to be exact and reproducible, and later get
handed to the LLM purely for explanation, not computation.
"""


def calculate_metrics(current_units: int | None = None, previous_units: int | None = None, bill_amount: float | None = None) -> dict:
    """Core deterministic metrics comparing this bill to the last one.
    Handles None inputs by treating them as zero where appropriate.
    """
    # Default missing values to zero to avoid TypeError
    cur_units = current_units or 0
    prev_units = previous_units or 0
    bill = bill_amount or 0.0
    difference = cur_units - prev_units
    
    if prev_units > 0:
        percentage_change = round((difference / prev_units) * 100, 2)
    else:
        percentage_change = None  # avoid divide-by-zero on a first bill
    
    cost_per_unit = round(bill / cur_units, 2) if cur_units else None
    
    trend = "increased" if difference > 0 else ("decreased" if difference < 0 else "unchanged")
    
    return {
        "difference": difference,
        "percentage_change": percentage_change,
        "trend": trend,
        "cost_per_unit": cost_per_unit,
    }

# Removed duplicate legacy block after return statement



def energy_score(percentage_change: float, current_units: int) -> dict:
    """
    A simple, explicitly-labelled WattWise Energy Score (0-100).
    NOT an official utility/government rating -- must always be
    presented to the user with that caveat.
    """
    score = 100

    if percentage_change is not None:
        if percentage_change > 0:
            score -= min(percentage_change, 70)  # cap the penalty
    if current_units > 600:
        score -= 20
    elif current_units > 400:
        score -= 10
    elif current_units > 250:
        score -= 3

    score = max(0, min(100, round(score)))

    if score >= 90:
        rating = "Excellent"
    elif score >= 75:
        rating = "Good"
    elif score >= 50:
        rating = "Average"
    elif score >= 25:
        rating = "High Consumption"
    else:
        rating = "Very High Consumption"

    return {"score": score, "rating": rating}


# ---------------------------------------------------------------------------
# Phase 6: Appliance usage -> estimated monthly kWh, with duty-cycle factors
# so we're not just multiplying by rated max wattage.
# ---------------------------------------------------------------------------

APPLIANCES = {
    "AC": {"wattage": 1500, "duty_cycle": 0.65},
    "Refrigerator": {"wattage": 200, "duty_cycle": 0.35},
    "TV": {"wattage": 100, "duty_cycle": 1.0},
    "Washing Machine": {"wattage": 500, "duty_cycle": 1.0},
    "Water Heater": {"wattage": 2000, "duty_cycle": 1.0},
    "Lighting": {"wattage": 60, "duty_cycle": 1.0},
}

# BEE (Bureau of Energy Efficiency) star ratings translate roughly to these
# efficiency multipliers vs an unrated/1-star baseline appliance. Approximate
# (real savings vary by brand/model) -- surfaced as a note in the UI.
STAR_RATING_MULTIPLIERS = {1: 1.00, 2: 0.92, 3: 0.84, 4: 0.76, 5: 0.68}


def estimate_appliance_consumption(appliance: str, hours_per_day: float, days: int = 30,
                                    star_rating: int | None = None) -> float:
    """Monthly kWh = (Wattage * hours/day * days * duty_cycle * star_multiplier) / 1000
    star_rating (1-5) is optional -- omit it for the original flat estimate."""
    if appliance not in APPLIANCES:
        raise ValueError(f"Unknown appliance: {appliance}. Add it to APPLIANCES first.")

    spec = APPLIANCES[appliance]
    multiplier = STAR_RATING_MULTIPLIERS.get(star_rating, 1.0) if star_rating else 1.0
    kwh = (spec["wattage"] * hours_per_day * days * spec["duty_cycle"] * multiplier) / 1000
    return round(kwh, 2)


def appliance_breakdown(usage: dict, days: int = 30, star_ratings: dict | None = None) -> dict:
    """
    usage: {"AC": 8, "TV": 3, "Refrigerator": 24, ...}  (hours/day)
    star_ratings: optional {"AC": 5, ...} (1-5, BEE stars)
    Returns each appliance's estimated kWh and its % share of the total.
    """
    star_ratings = star_ratings or {}
    consumption = {
        name: estimate_appliance_consumption(name, hours, days, star_ratings.get(name))
        for name, hours in usage.items()
    }
    total = sum(consumption.values()) or 1  # avoid divide-by-zero
    return {
        name: {"kwh": kwh, "percent_share": round((kwh / total) * 100, 1)}
        for name, kwh in consumption.items()
    }


# ---------------------------------------------------------------------------
# Phase 9: Savings simulator -- same formula, just comparing two scenarios.
# ---------------------------------------------------------------------------

def simulate_savings(appliance: str, current_hours: float, new_hours: float,
                       cost_per_unit: float | None, days: int = 30, star_rating: int | None = None) -> dict:
    """Simulate savings with optional cost_per_unit and star_rating.
    If cost_per_unit is None, savings will be None.
    """
    current_kwh = estimate_appliance_consumption(appliance, current_hours, days, star_rating)
    new_kwh = estimate_appliance_consumption(appliance, new_hours, days, star_rating)
    reduction_kwh = round(current_kwh - new_kwh, 2)
    savings = round(reduction_kwh * cost_per_unit, 2) if cost_per_unit is not None else None

    return {
        "current_kwh": current_kwh,
        "new_kwh": new_kwh,
        "reduction_kwh": reduction_kwh,
        "estimated_savings_rupees": savings,
    }


if __name__ == "__main__":
    metrics = calculate_metrics(420, 290, 3650)
    print("Metrics:", metrics)

    score = energy_score(metrics["percentage_change"], 420)
    print("Energy score:", score)

    breakdown = appliance_breakdown({"AC": 8, "TV": 3, "Refrigerator": 24})
    print("Appliance breakdown:", breakdown)

    savings = simulate_savings("AC", 8, 6, metrics["cost_per_unit"])
    print("Savings simulation:", savings)
