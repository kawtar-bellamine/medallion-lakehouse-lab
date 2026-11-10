# Data dictionary (Gold layer)

## fact_sales
One row per order line. Keys: date_key (yyyymmdd), order_id, line_no, channel, customer_key, product_code.
amount_chf is quantity times unit price in Swiss francs, rounded to the centime. net_amount_chf equals amount_chf
for completed orders and 0 for returned or cancelled orders. Revenue in every report means the sum of net_amount_chf.

## dim_product
Product catalogue: product_code, category (watch, strap, service, accessory), French and German names,
list_price_chf and launch_year. Product codes start with HA-.

## dim_channel
Five sales channels: web_ch (Swiss web shop), web_eu (European web shop, prices in euros converted to francs),
store_geneve, store_lausanne and store_zurich. channel_type is Web or Store, market is CH or EU.

## dim_customer
customer_key is a SHA-256 hash of the ERP customer id. It carries the first order date, the number of orders and
the main channel. No name, email or address is stored in Silver or Gold.

## kpi_daily_channel
Revenue, completed orders, returned orders, average order value and return rate per day and channel.
Average order value is revenue divided by completed orders. Return rate is returned orders divided by all orders.

## kpi_web_funnel
Distinct web sessions per day at each step: page_view, product_view, add_to_cart, checkout, plus web orders.
Conversion rate is web orders divided by sessions with a page view.
