"""Canonical Nigerian state labels — keep in sync with foodstuff-store-code / foodstuff-api."""

NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT (Abuja)", "Gombe",
    "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos",
    "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
]

_NIGERIAN_STATES_LOWER = {s.lower(): s for s in NIGERIAN_STATES}

_FCT_ALIASES = {
    "fct": "FCT (Abuja)",
    "abuja": "FCT (Abuja)",
    "fct abuja": "FCT (Abuja)",
    "fct (abuja)": "FCT (Abuja)",
    "federal capital territory": "FCT (Abuja)",
    "federal capital territory abuja": "FCT (Abuja)",
}

CUSTOMER_TYPES = ("b2b", "b2c")


def normalize_city(city: str | None) -> str | None:
    if city is None:
        return None
    raw = " ".join(str(city).strip().split())
    if not raw:
        return ""
    key = " ".join(raw.lower().replace("-", " ").split())
    if key in _FCT_ALIASES:
        return _FCT_ALIASES[key]
    return _NIGERIAN_STATES_LOWER.get(raw.lower(), raw)


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    cat = str(category).strip().lower()
    if cat in CUSTOMER_TYPES:
        return cat
    return category
