"""Card-linked offers. Sample data for the personal app -- replace/extend with
offers you actually see from your issuers.

discount_pct / max_discount apply on top of normal card rewards.
Match: `cards` (specific card ids) or `issuers` (any card from that issuer).
`weekdays` (optional): days the offer runs, Monday=0 ... Sunday=6.
"""

OFFERS: list[dict] = [
    {"id": "o1", "title": "10% off on Swiggy (Tuesdays)", "merchant": "swiggy", "issuers": ["HDFC Bank"], "discount_pct": 10, "max_discount": 100, "min_txn": 399, "valid_till": "2026-12-31", "weekdays": [1]},
    {"id": "o2", "title": "Flat Rs.150 off on Zomato", "merchant": "zomato", "issuers": ["Axis Bank"], "discount_pct": None, "flat_discount": 150, "min_txn": 699, "valid_till": "2026-11-30"},
    {"id": "o3", "title": "10% instant discount on Amazon Great Indian Festival", "merchant": "amazon", "issuers": ["SBI Card", "ICICI Bank"], "discount_pct": 10, "max_discount": 1500, "min_txn": 5000, "valid_till": "2026-10-31"},
    {"id": "o4", "title": "Big Billion Days: 10% off", "merchant": "flipkart", "issuers": ["Axis Bank", "ICICI Bank"], "discount_pct": 10, "max_discount": 1750, "min_txn": 5000, "valid_till": "2026-10-31"},
    {"id": "o5", "title": "15% off on MakeMyTrip domestic flights", "merchant": "makemytrip", "issuers": ["HDFC Bank", "ICICI Bank"], "discount_pct": 15, "max_discount": 2000, "min_txn": 6000, "valid_till": "2026-12-15"},
    {"id": "o6", "title": "Buy 1 Get 1 on BookMyShow", "merchant": "bookmyshow", "cards": ["axis_magnus", "icici_emeralde"], "discount_pct": 50, "max_discount": 500, "min_txn": 400, "valid_till": "2026-12-31"},
    {"id": "o7", "title": "20% off at Taj restaurants", "merchant": "taj", "cards": ["hdfc_infinia", "icici_emeralde", "hdfc_dcb"], "discount_pct": 20, "max_discount": 3000, "min_txn": 2000, "valid_till": "2027-03-31"},
    {"id": "o8", "title": "Rs.500 off on Myntra", "merchant": "myntra", "issuers": ["HDFC Bank"], "flat_discount": 500, "min_txn": 3000, "valid_till": "2026-11-15"},
    {"id": "o9", "title": "5% off at Croma (Neu members)", "merchant": "croma", "cards": ["tata_neu_infinity"], "discount_pct": 5, "max_discount": 2500, "min_txn": 10000, "valid_till": "2027-01-31"},
    {"id": "o10", "title": "Uber: 20% off 3 rides", "merchant": "uber", "issuers": ["American Express"], "discount_pct": 20, "max_discount": 75, "min_txn": 150, "valid_till": "2026-10-31"},
    {"id": "o11", "title": "Fuel surcharge waiver (1%)", "merchant": None, "category": "fuel", "issuers": ["SBI Card", "HDFC Bank", "Axis Bank", "ICICI Bank", "IDFC FIRST Bank"], "discount_pct": 1, "max_discount": 250, "min_txn": 400, "valid_till": "2027-03-31"},
    {"id": "o12", "title": "Rs.1,000 off on Apple products", "merchant": "apple", "issuers": ["HDFC Bank", "ICICI Bank"], "flat_discount": 1000, "min_txn": 30000, "valid_till": "2026-12-31"},
    {"id": "o13", "title": "15% off on Marriott stays", "merchant": "marriott", "issuers": ["American Express"], "discount_pct": 15, "max_discount": 5000, "min_txn": 8000, "valid_till": "2027-02-28"},
    {"id": "o14", "title": "Flat 12% off Blinkit (min Rs.999)", "merchant": "blinkit", "issuers": ["HSBC", "IDFC FIRST Bank"], "discount_pct": 12, "max_discount": 150, "min_txn": 999, "valid_till": "2026-11-30"},
]
