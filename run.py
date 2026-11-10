"""End to end: generate the sources, run Bronze, Silver and Gold day by day, check idempotence and quality,
export Gold for Power BI, evaluate the documentation assistant, draw the figures.

    python run.py              # 30 days, about 4 minutes on a laptop
    python run.py --days 10    # faster
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import time
from pathlib import Path

from lakehouse import pipeline as P
from lakehouse import report
from lakehouse.generate import START, write_sources
from lakehouse.rag import Assistant, evaluate

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--work", default=str(ROOT / "work"))
    args = ap.parse_args()
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    injected = write_sources(work, days=args.days)
    spark = P.spark_session()
    spark.sparkContext.setLogLevel("ERROR")
    lake, landing = work / "lake", work / "landing"
    t0, days = time.time(), []
    for i in range(args.days):
        day = str(START + dt.timedelta(days=i))
        P.bronze(spark, lake, landing, day)
        days.append(P.silver(spark, lake, landing, day))
        print(days[-1])
    gold = P.gold(spark, lake, landing)
    runtime = time.time() - t0

    # idempotence: replay a day that received late lines, Gold must not move
    before = {r["date_key"]: r["revenue_chf"] for r in spark.read.parquet(str(lake / "gold" / "kpi_daily_channel"))
              .groupBy("date_key").sum("revenue_chf").withColumnRenamed("sum(revenue_chf)", "revenue_chf").collect()}
    replay = str(START + dt.timedelta(days=min(5, args.days - 1)))
    P.bronze(spark, lake, landing, replay); P.silver(spark, lake, landing, replay); P.gold(spark, lake, landing)
    after = {r["date_key"]: r["revenue_chf"] for r in spark.read.parquet(str(lake / "gold" / "kpi_daily_channel"))
             .groupBy("date_key").sum("revenue_chf").withColumnRenamed("sum(revenue_chf)", "revenue_chf").collect()}
    idempotent = all(abs(before[k] - after.get(k, 0)) < 0.005 for k in before)

    silver = spark.read.parquet(str(lake / "silver" / "order_lines"))
    q = spark.read.parquet(str(lake / "silver" / "quarantine"))
    by_rule = {r["rule"]: r["count"] for r in q.groupBy("rule").count().collect()}
    late = silver.where("cast(order_date as string) != _batch_date").count()
    quality = {
        "duplicates": {"injected": injected["duplicate_line"], "removed": sum(d["duplicates_removed"] for d in days)},
        "missing_customer": {"injected": injected["missing_customer"], "caught": by_rule.get("customer_present", 0)},
        "zero_quantity": {"injected": injected["zero_quantity"], "caught": by_rule.get("quantity_positive", 0)},
        "price_in_cents": {"injected": injected["price_in_cents"], "caught": by_rule.get("price_plausible", 0)},
        "unknown_product": {"injected": injected["unknown_product"], "caught": by_rule.get("known_product", 0)},
        "swiss_date_format": {"injected": injected["swiss_date_format"], "parsed": injected["swiss_date_format"]
                              - by_rule.get("timestamp_parsed", 0)},
        "late_arrival": {"injected": injected["late_arrival"], "merged_into_order_day": late},
    }
    export = ROOT / "powerbi" / "export"
    if export.exists():
        shutil.rmtree(export)
    for name in gold["rows"]:
        (spark.read.parquet(str(lake / "gold" / name)).coalesce(1).write.option("header", True)
         .csv(str(export / name)))
        part = next((export / name).glob("part-*.csv"))
        part.rename(export / f"{name}.csv"); shutil.rmtree(export / name)

    dq = [{"day": d["day"], "lines_received": d["bronze_rows"], "duplicates_removed": d["duplicates_removed"],
           "quarantined": d["quarantined_rows"], "late_lines_merged": d["late_lines_day"],
           "quarantine_rate": round(d["quarantined_rows"] / d["bronze_rows"], 5),
           **{f"rule_{k}": v for k, v in d["by_rule"].items()}} for d in days]
    import csv
    keys = sorted({k for r in dq for k in r}, key=lambda k: (k not in dq[0], k))
    with open(export / "dq_daily.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval=0); w.writeheader(); w.writerows(dq)

    rag = evaluate(Assistant(), ROOT / "eval" / "rag_eval.json")
    heldout = evaluate(Assistant(), ROOT / "eval" / "rag_heldout.json")
    summary = {"days": args.days, "runtime_s": round(runtime, 1), "bronze_rows": sum(d["bronze_rows"] for d in days),
               "silver_rows": silver.count(), "quarantined_rows": q.select("order_id", "line_no").distinct().count(),
               "quality": quality, "gold": gold, "idempotent_replay": {"day": replay, "gold_unchanged": idempotent},
               "rag": {k: v for k, v in rag.items() if k != "rows"}, "rag_rows": rag["rows"],
               "rag_heldout": {k: v for k, v in heldout.items() if k != "rows"}, "rag_heldout_rows": heldout["rows"]}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    report.build(ROOT, export, summary)
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("_rows")}, indent=2, default=str))


if __name__ == "__main__":
    main()
