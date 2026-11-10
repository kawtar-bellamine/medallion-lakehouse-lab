"""Medallion pipeline in PySpark: the same code runs locally and on Databricks.

Bronze  raw files as received, all columns as text, plus ingestion metadata; one partition per batch date.
Silver  typed, deduplicated, conformed (CHF, one timestamp format), personal data hashed, contract rules enforced;
        rows that break a rule go to a quarantine table with the rule name. Partitioned by business date, so a
        line that arrives a day late lands in the right day.
Gold    star schema for Power BI (fact_sales, dimensions) and daily KPI tables.
Every write overwrites only the partitions it touches: running a day twice gives the same lake.
"""
from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

EUR_TO_CHF = 0.94


def spark_session() -> SparkSession:
    return (SparkSession.builder.master("local[2]").appName("medallion-lakehouse-lab")
            .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "4")
            .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
            .config("spark.sql.session.timeZone", "Europe/Zurich").getOrCreate())


def _exists(path: Path) -> bool:
    return path.exists() and any(path.rglob("*.parquet"))


# ------------------------------------------------------------------ Bronze
def bronze(spark: SparkSession, lake: Path, landing: Path, day: str) -> int:
    orders = (spark.read.option("header", True).option("inferSchema", False).csv(str(landing / "erp" / f"orders_{day}.csv"))
              .withColumn("_source_file", F.lit(f"erp/orders_{day}.csv"))
              .withColumn("_ingested_at", F.current_timestamp()).withColumn("_batch_date", F.lit(day)))
    orders.write.mode("overwrite").partitionBy("_batch_date").parquet(str(lake / "bronze" / "erp_orders"))
    events = (spark.read.json(str(landing / "web" / f"events_{day}.jsonl"))
              .withColumn("_ingested_at", F.current_timestamp()).withColumn("_batch_date", F.lit(day)))
    events.write.mode("overwrite").partitionBy("_batch_date").parquet(str(lake / "bronze" / "web_events"))
    return orders.count()


# ------------------------------------------------------------------ Silver
def silver(spark: SparkSession, lake: Path, landing: Path, day: str) -> dict:
    products = spark.read.option("header", True).option("inferSchema", True).csv(str(landing / "ref" / "products.csv"))
    raw = spark.read.parquet(str(lake / "bronze" / "erp_orders")).where(F.col("_batch_date") == day)
    ts = F.coalesce(F.to_timestamp("order_ts", "yyyy-MM-dd HH:mm:ss"), F.to_timestamp("order_ts", "dd.MM.yyyy HH:mm:ss"))
    typed = (raw.withColumn("order_ts", ts).withColumn("order_date", F.to_date("order_ts"))
             .withColumn("line_no", F.col("line_no").cast("int")).withColumn("quantity", F.col("quantity").cast("int"))
             .withColumn("unit_price", F.col("unit_price").cast("double"))
             .withColumn("unit_price_chf", F.when(F.col("currency") == "EUR", F.col("unit_price") * EUR_TO_CHF)
                         .otherwise(F.col("unit_price")))
             .withColumn("customer_key", F.when(F.length(F.coalesce("customer_id", F.lit(""))) > 0,
                                                F.sha2(F.col("customer_id"), 256)))
             .drop("customer_email", "customer_id_raw")
             .join(products.select("product_code", "list_price_chf"), "product_code", "left"))
    checks = {
        "customer_present": F.col("customer_key").isNotNull(),
        "quantity_positive": F.col("quantity") > 0,
        "known_product": F.col("list_price_chf").isNotNull(),
        "price_plausible": F.col("list_price_chf").isNull()       # judged only when the product is known
        | F.col("unit_price_chf").between(0.5 * F.col("list_price_chf"), 1.2 * F.col("list_price_chf")),
        "timestamp_parsed": F.col("order_ts").isNotNull(),
    }
    failed = F.array_compact(F.array(*[F.when(~F.coalesce(c, F.lit(False)), F.lit(n)) for n, c in checks.items()]))
    checked = typed.withColumn("failed_rules", failed)
    w = Window.partitionBy("order_id", "line_no").orderBy("_ingested_at")
    deduped = checked.withColumn("_rn", F.row_number().over(w))
    duplicates = deduped.where("_rn > 1").count()
    deduped = deduped.where("_rn = 1").drop("_rn")
    good = deduped.where(F.size("failed_rules") == 0).drop("failed_rules", "customer_id", "list_price_chf")
    bad = deduped.where(F.size("failed_rules") > 0)
    quarantine = bad.select("order_id", "line_no", "_source_file", "_batch_date", F.explode("failed_rules").alias("rule"))
    quarantine.write.mode("overwrite").partitionBy("_batch_date").parquet(str(lake / "silver" / "quarantine"))

    # merge into Silver by business date: late lines join the day they belong to; reruns change nothing
    target = lake / "silver" / "order_lines"
    dates = [r.order_date for r in good.select("order_date").distinct().collect()]
    if _exists(target):
        existing = spark.read.parquet(str(target)).where(F.col("order_date").isin(dates))
        good = existing.unionByName(good)
        good = (good.withColumn("_rn", F.row_number().over(Window.partitionBy("order_id", "line_no")
                                                           .orderBy("_ingested_at"))).where("_rn = 1").drop("_rn"))
    good = good.localCheckpoint()                      # break lineage before overwriting what was read
    good.write.mode("overwrite").partitionBy("order_date").parquet(str(target))

    ev = spark.read.parquet(str(lake / "bronze" / "web_events")).where(F.col("_batch_date") == day)
    ev = (ev.withColumn("ts", F.to_timestamp("ts")).withColumn("event_date", F.to_date("ts"))
          .where(F.col("event").isin("page_view", "product_view", "add_to_cart", "checkout")))
    ev.write.mode("overwrite").partitionBy("_batch_date").parquet(str(lake / "silver" / "web_events"))
    q = {r["rule"]: r["count"] for r in quarantine.groupBy("rule").count().collect()}
    return {"day": day, "bronze_rows": raw.count(), "duplicates_removed": duplicates,
            "quarantined_rows": bad.count(), "by_rule": q,
            "late_lines": good.where(F.col("_batch_date") != F.col("order_date").cast("string")).count(),
            "late_lines_day": typed.where(F.col("order_date").cast("string") != F.lit(day)).count()}


# ------------------------------------------------------------------ Gold
def gold(spark: SparkSession, lake: Path, landing: Path) -> dict:
    s = spark.read.parquet(str(lake / "silver" / "order_lines"))
    products = spark.read.option("header", True).option("inferSchema", True).csv(str(landing / "ref" / "products.csv"))
    fact = (s.select(F.date_format("order_date", "yyyyMMdd").cast("int").alias("date_key"), "order_id", "line_no",
                     "channel", "customer_key", "product_code", "quantity", "status",
                     F.round(F.col("quantity") * F.col("unit_price_chf"), 2).alias("amount_chf"))
            .withColumn("net_amount_chf", F.when(F.col("status") == "completed", F.col("amount_chf")).otherwise(0.0)))
    dim_product = products.select("product_code", "category", "name_fr", "name_de", "list_price_chf", "launch_year")
    dim_channel = spark.createDataFrame(
        [("web_ch", "Web", "CH"), ("web_eu", "Web", "EU"), ("store_geneve", "Store", "CH"),
         ("store_lausanne", "Store", "CH"), ("store_zurich", "Store", "CH")], ["channel", "channel_type", "market"])
    dates = s.select("order_date").distinct()
    dim_date = dates.select(F.date_format("order_date", "yyyyMMdd").cast("int").alias("date_key"),
                            F.col("order_date").alias("date"), F.dayofweek("order_date").alias("weekday"),
                            F.weekofyear("order_date").alias("iso_week"), F.date_format("order_date", "yyyy-MM").alias("month"))
    dim_customer = (s.groupBy("customer_key").agg(F.min("order_date").alias("first_order_date"),
                                                  F.countDistinct("order_id").alias("orders"),
                                                  F.mode("channel").alias("main_channel")))
    kpi = (fact.groupBy("date_key", "channel").agg(
        F.round(F.sum("net_amount_chf"), 2).alias("revenue_chf"),
        F.countDistinct(F.when(F.col("status") == "completed", F.col("order_id"))).alias("orders"),
        F.countDistinct(F.when(F.col("status") == "returned", F.col("order_id"))).alias("returned_orders"),
        F.countDistinct("order_id").alias("all_orders"))
        .withColumn("avg_order_value_chf", F.round(F.col("revenue_chf") / F.col("orders"), 2))
        .withColumn("return_rate", F.round(F.col("returned_orders") / F.col("all_orders"), 4)))
    ev = spark.read.parquet(str(lake / "silver" / "web_events"))
    funnel = (ev.groupBy(F.date_format("event_date", "yyyyMMdd").cast("int").alias("date_key")).pivot(
        "event", ["page_view", "product_view", "add_to_cart", "checkout"]).agg(F.countDistinct("session")))
    web_orders = fact.where(F.col("channel").startswith("web")).groupBy("date_key").agg(
        F.countDistinct("order_id").alias("web_orders"))
    funnel = funnel.join(web_orders, "date_key", "left").withColumn(
        "conversion_rate", F.round(F.col("web_orders") / F.col("page_view"), 4))
    kpi_category = (fact.join(dim_product.select("product_code", "category"), "product_code")
                    .join(dim_channel, "channel")
                    .groupBy(F.substring(F.col("date_key").cast("string"), 1, 6).alias("month"), "category",
                             "channel_type")
                    .agg(F.round(F.sum("net_amount_chf"), 2).alias("revenue_chf"),
                         F.sum(F.when(F.col("status") == "completed", F.col("quantity"))).alias("units")))
    first = dim_customer.select("customer_key", F.date_format("first_order_date", "yyyyMMdd").cast("int")
                                .alias("first_key"))
    kpi_customers = (fact.join(first, "customer_key").groupBy("date_key").agg(
        F.countDistinct(F.when(F.col("date_key") == F.col("first_key"), F.col("customer_key"))).alias("new_customers"),
        F.countDistinct(F.when(F.col("date_key") > F.col("first_key"), F.col("customer_key")))
        .alias("returning_customers")))
    out = {"fact_sales": fact, "dim_product": dim_product, "dim_channel": dim_channel, "dim_date": dim_date,
           "dim_customer": dim_customer, "kpi_daily_channel": kpi, "kpi_web_funnel": funnel, "kpi_category_month": kpi_category,
           "kpi_customers_daily": kpi_customers}
    for name, df in out.items():
        df.write.mode("overwrite").parquet(str(lake / "gold" / name))
    silver_total = s.where("status = 'completed'").select(
        F.sum(F.round(F.col("quantity") * F.col("unit_price_chf"), 2))).first()[0]
    gold_total = spark.read.parquet(str(lake / "gold" / "kpi_daily_channel")).select(F.sum("revenue_chf")).first()[0]
    return {"rows": {k: spark.read.parquet(str(lake / "gold" / k)).count() for k in out},
            "reconciliation": {"silver_revenue_chf": round(silver_total, 2), "gold_revenue_chf": round(gold_total, 2),
                               "difference_chf": round(gold_total - silver_total, 2)}}
