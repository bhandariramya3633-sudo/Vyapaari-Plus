"""GST rules that change over time.

Verify these on the official GST and e-way bill portals before a release.
"""

from decimal import Decimal

# An e-way bill is needed when the invoice value is above this amount (rupees).
E_WAY_BILL_THRESHOLD = Decimal("50000")

# Largest distance, in km, accepted on the e-way bill form.
MAX_TRANSPORT_DISTANCE_KM = 4000
