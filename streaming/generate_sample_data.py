"""
Generates a small, schema-accurate stand-in for IBM's synthetic credit card
transactions dataset (Kaggle/TabFormer), so the pipeline can be run end-to-end
without needing a Kaggle account or a multi-gigabyte download.

Swap this file for the real dataset (see streaming/README.md) once you want
realistic fraud patterns and true 24M-row scale; the column layout matches
exactly, so kafka_producer_replay.py needs no changes either way.
"""

import csv
import random
from datetime import datetime, timedelta

random.seed(42)

N_ROWS = 5000
N_USERS = 200
N_MERCHANTS = 60
DAYS_BACK = 30

MCC_CODES = ["5411", "5812", "5541", "4899", "5732", "5311", "4111", "5942", "7995", "5999"]
STATES = ["NY", "CA", "TX", "IL", "WA", "MI", "FL", "OH", "GA", "PA"]

merchants = [
    {
        "name": str(random.randint(-9_999_999_999, -1_000_000_000)),  # IBM dataset uses signed int merchant ids
        "city": random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Seattle", "Detroit"]),
        "state": random.choice(STATES),
        "zip": f"{random.randint(10000, 99999)}",
        "mcc": random.choice(MCC_CODES),
    }
    for _ in range(N_MERCHANTS)
]

end = datetime.now()
start = end - timedelta(days=DAYS_BACK)

rows = []
for _ in range(N_ROWS):
    user = random.randint(0, N_USERS - 1)
    card = random.randint(0, 2)
    ts = start + (end - start) * random.random()
    merchant = random.choice(merchants)
    amount = round(random.lognormvariate(3.2, 1.1), 2)  # skews toward small purchases, occasional large ones
    is_fraud = random.random() < 0.01
    has_error = random.random() < 0.02

    rows.append(
        {
            "User": user,
            "Card": card,
            "Year": ts.year,
            "Month": ts.month,
            "Day": ts.day,
            "Time": ts.strftime("%H:%M"),
            "Amount": f"${amount:.2f}",
            "Use Chip": random.choice(["Chip Transaction", "Swipe Transaction", "Online Transaction"]),
            "Merchant Name": merchant["name"],
            "Merchant City": merchant["city"],
            "Merchant State": merchant["state"],
            "Zip": merchant["zip"],
            "MCC": merchant["mcc"],
            "Errors?": "Bad PIN" if has_error else "",
            "Is Fraud?": "Yes" if is_fraud else "No",
        }
    )

rows.sort(key=lambda r: (r["Year"], r["Month"], r["Day"], r["Time"]))

out_path = "data/sample_transactions.csv"
with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {len(rows)} rows to {out_path}")
