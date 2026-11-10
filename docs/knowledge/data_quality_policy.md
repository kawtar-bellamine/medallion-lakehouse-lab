# Data quality policy

Every order line is checked against the Silver contract before it can reach Gold. A line that breaks a rule is
written to the quarantine table with the name of the rule and the source file; it is never corrected silently.

Rules: customer_present (the customer id is not empty), quantity_positive (quantity above zero), known_product
(the product code exists in the catalogue), price_plausible (unit price between 50 % and 120 % of the list price;
a price one hundred times too high usually means the till sent centimes), timestamp_parsed (the timestamp is in the
ISO format or in the Swiss format dd.mm.yyyy used by the store tills).

Duplicates: the ERP interface sometimes resends a line. Silver keeps one row per order_id and line_no, the first
one ingested.

Late lines: a line can arrive in the next day's file. Silver is partitioned by business date, so the late line is
merged into the day of the order and the KPIs of that day are recomputed.

The quarantine is reviewed every morning by the data steward of the ERP team, who fixes the source and replays the day.
