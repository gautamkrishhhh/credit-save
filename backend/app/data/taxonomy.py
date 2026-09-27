"""Spend taxonomy: categories and known merchants (with the aliases that show
up in bank SMS / statement descriptors).

This is the vocabulary shared by the rewards engine, the ML categorizer and the
assistant's entity extractor.
"""

CATEGORIES: dict[str, str] = {
    "food_delivery": "Food Delivery",
    "dining": "Dining",
    "grocery": "Groceries",
    "online_shopping": "Online Shopping",
    "fashion": "Fashion & Beauty",
    "electronics": "Electronics",
    "travel_flights": "Flights",
    "travel_hotels": "Hotels",
    "cabs": "Cabs & Transit",
    "fuel": "Fuel",
    "utilities": "Utilities & Bills",
    "telecom": "Mobile & Broadband",
    "entertainment": "Entertainment & OTT",
    "health": "Health & Pharmacy",
    "education": "Education",
    "insurance": "Insurance",
    "rent": "Rent",
    "government": "Government & Taxes",
    "wallet_load": "Wallet Loads",
    "jewellery": "Jewellery",
    "others": "Others",
}

# merchant_id -> (display name, category, aliases used in SMS/statements)
MERCHANTS: dict[str, tuple[str, str, list[str]]] = {
    "swiggy": ("Swiggy", "food_delivery", ["swiggy", "swiggy instamart", "bundl technologies"]),
    "zomato": ("Zomato", "food_delivery", ["zomato", "zomato ltd", "eternal ltd"]),
    "dominos": ("Domino's", "dining", ["dominos", "jubilant foodworks", "domino's pizza"]),
    "starbucks": ("Starbucks", "dining", ["starbucks", "tata starbucks"]),
    "mcdonalds": ("McDonald's", "dining", ["mcdonalds", "hardcastle restaurants", "mcd"]),
    "restaurant": ("Restaurant", "dining", ["restaurant", "cafe", "bistro", "dhaba", "bar and kitchen", "brewery"]),
    "bigbasket": ("BigBasket", "grocery", ["bigbasket", "bb now", "supermarket grocery supplies"]),
    "blinkit": ("Blinkit", "grocery", ["blinkit", "grofers"]),
    "zepto": ("Zepto", "grocery", ["zepto", "kiranakart"]),
    "dmart": ("DMart", "grocery", ["dmart", "avenue supermarts"]),
    "amazon": ("Amazon", "online_shopping", ["amazon", "amazon pay", "amzn", "amazon seller services"]),
    "flipkart": ("Flipkart", "online_shopping", ["flipkart", "flipkart internet"]),
    "meesho": ("Meesho", "online_shopping", ["meesho", "fashnear technologies"]),
    "myntra": ("Myntra", "fashion", ["myntra", "myntra designs"]),
    "ajio": ("AJIO", "fashion", ["ajio", "reliance retail ajio"]),
    "nykaa": ("Nykaa", "fashion", ["nykaa", "fsn e-commerce"]),
    "croma": ("Croma", "electronics", ["croma", "infiniti retail"]),
    "reliance_digital": ("Reliance Digital", "electronics", ["reliance digital", "resd"]),
    "apple": ("Apple Store", "electronics", ["apple india", "apple store", "apple.com/bill"]),
    "makemytrip": ("MakeMyTrip", "travel_flights", ["makemytrip", "mmt"]),
    "cleartrip": ("Cleartrip", "travel_flights", ["cleartrip"]),
    "indigo": ("IndiGo", "travel_flights", ["indigo", "interglobe aviation"]),
    "air_india": ("Air India", "travel_flights", ["air india", "airindia"]),
    "smartbuy": ("HDFC SmartBuy", "travel_flights", ["smartbuy", "hdfc smartbuy"]),
    "travel_edge": ("Axis Travel Edge", "travel_flights", ["travel edge", "axis travel edge"]),
    "scapia_travel": ("Scapia Travel", "travel_flights", ["scapia travel"]),
    "taj": ("Taj Hotels", "travel_hotels", ["taj", "ihcl", "indian hotels company"]),
    "marriott": ("Marriott", "travel_hotels", ["marriott", "jw marriott", "courtyard"]),
    "oyo": ("OYO", "travel_hotels", ["oyo", "oravel stays"]),
    "agoda": ("Agoda", "travel_hotels", ["agoda"]),
    "uber": ("Uber", "cabs", ["uber", "uber india"]),
    "ola": ("Ola", "cabs", ["ola", "ani technologies", "olacabs"]),
    "irctc": ("IRCTC", "cabs", ["irctc", "indian railway"]),
    "metro": ("Metro Rail", "cabs", ["metro rail", "bmrcl", "dmrc"]),
    "iocl": ("Indian Oil", "fuel", ["iocl", "indian oil", "indianoil"]),
    "hpcl": ("HP Petrol", "fuel", ["hpcl", "hindustan petroleum", "hp petrol"]),
    "bpcl": ("Bharat Petroleum", "fuel", ["bpcl", "bharat petroleum"]),
    "shell": ("Shell", "fuel", ["shell"]),
    "bescom": ("Electricity Bill", "utilities", ["bescom", "tata power", "adani electricity", "msedcl", "electricity"]),
    "gas_bill": ("Gas Bill", "utilities", ["indraprastha gas", "mahanagar gas", "gas bill", "piped gas"]),
    "airtel": ("Airtel", "telecom", ["airtel", "bharti airtel"]),
    "jio": ("Jio", "telecom", ["jio", "reliance jio"]),
    "vi": ("Vi", "telecom", ["vodafone idea", "vi postpaid"]),
    "netflix": ("Netflix", "entertainment", ["netflix"]),
    "spotify": ("Spotify", "entertainment", ["spotify"]),
    "hotstar": ("JioHotstar", "entertainment", ["hotstar", "jiohotstar", "disney"]),
    "bookmyshow": ("BookMyShow", "entertainment", ["bookmyshow", "bigtree entertainment"]),
    "pvr": ("PVR INOX", "entertainment", ["pvr", "inox"]),
    "apollo": ("Apollo Pharmacy", "health", ["apollo pharmacy", "apollo 24x7", "apollo hospitals"]),
    "tata_1mg": ("Tata 1mg", "health", ["1mg", "tata 1mg"]),
    "pharmeasy": ("PharmEasy", "health", ["pharmeasy"]),
    "cult": ("cult.fit", "health", ["cult.fit", "cultfit", "curefit"]),
    "byjus": ("Coursera/EdTech", "education", ["coursera", "udemy", "byjus", "unacademy"]),
    "school_fees": ("School Fees", "education", ["school fees", "university", "college fee"]),
    "lic": ("LIC", "insurance", ["lic", "life insurance corporation"]),
    "policybazaar": ("Policybazaar", "insurance", ["policybazaar", "hdfc ergo", "icici lombard", "star health"]),
    "cred_rent": ("Rent (CRED/NoBroker)", "rent", ["cred rent", "nobroker rent", "rent payment", "housing rent"]),
    "income_tax": ("Income Tax", "government", ["income tax", "incometax", "gst payment", "govt"]),
    "paytm_wallet": ("Paytm Wallet", "wallet_load", ["paytm wallet", "wallet load", "phonepe wallet", "amazon pay balance"]),
    "tanishq": ("Tanishq", "jewellery", ["tanishq", "titan company", "kalyan jewellers", "malabar gold"]),
    "ikea": ("IKEA", "others", ["ikea"]),
    "decathlon": ("Decathlon", "others", ["decathlon"]),
}


def merchant_category(merchant_id: str | None) -> str | None:
    if merchant_id and merchant_id in MERCHANTS:
        return MERCHANTS[merchant_id][1]
    return None


def merchant_name(merchant_id: str | None) -> str | None:
    if merchant_id and merchant_id in MERCHANTS:
        return MERCHANTS[merchant_id][0]
    return None
