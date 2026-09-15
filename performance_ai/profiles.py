from __future__ import annotations

PROFILE_DESCRIPTIONS = {
    "EFFICIENCY": "Favor battery life and low background activity.",
    "BALANCED": "Keep Windows near its normal balanced behavior.",
    "DEVELOPMENT": "Favor interactive CPU responsiveness for coding and builds.",
    "DATA_SCIENCE": "Favor sustained CPU/RAM/disk throughput for data workloads.",
    "LOCAL_AI": "Favor local inference while avoiding unnecessary background pressure.",
    "PERFORMANCE": "Favor sustained performance while plugged in.",
    "BATTERY_SAVER": "Protect remaining battery and reduce avoidable work.",
}

# These are desired *kinds* of installed Windows power schemes.
# The optimizer only activates a matching scheme if Windows already exposes it.
PROFILE_POWER_SCHEME_PREFERENCE = {
    "EFFICIENCY": ("power saver", "balanced"),
    "BATTERY_SAVER": ("power saver", "balanced"),
    "BALANCED": ("balanced",),
    "DEVELOPMENT": ("balanced", "high performance"),
    "DATA_SCIENCE": ("high performance", "ultimate performance", "balanced"),
    "LOCAL_AI": ("high performance", "ultimate performance", "balanced"),
    "PERFORMANCE": ("ultimate performance", "high performance", "balanced"),
}
