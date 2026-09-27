"""Loyalty programmes that card points can be transferred to.

`value_inr` is a conservative average value of one partner point/mile in
rupees when redeemed well (award flights / hotel nights). These are
illustrative estimates, not quotes.
"""

PARTNERS: dict[str, dict] = {
    "krisflyer": {"name": "Singapore KrisFlyer", "type": "airline", "value_inr": 1.2},
    "air_india": {"name": "Air India Maharaja Club", "type": "airline", "value_inr": 0.8},
    "qatar_avios": {"name": "Qatar Privilege Club (Avios)", "type": "airline", "value_inr": 1.2},
    "ba_avios": {"name": "British Airways Club (Avios)", "type": "airline", "value_inr": 1.1},
    "turkish": {"name": "Turkish Miles&Smiles", "type": "airline", "value_inr": 1.2},
    "etihad": {"name": "Etihad Guest", "type": "airline", "value_inr": 0.9},
    "emirates": {"name": "Emirates Skywards", "type": "airline", "value_inr": 0.7},
    "flying_blue": {"name": "Air France-KLM Flying Blue", "type": "airline", "value_inr": 1.0},
    "marriott": {"name": "Marriott Bonvoy", "type": "hotel", "value_inr": 0.7},
    "accor": {"name": "Accor Live Limitless", "type": "hotel", "value_inr": 1.8},
    "itc": {"name": "Club ITC", "type": "hotel", "value_inr": 0.8},
    "ihg": {"name": "IHG One Rewards", "type": "hotel", "value_inr": 0.45},
}
