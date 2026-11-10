import datetime as dt
from pathlib import Path

import pytest
import yaml
from pyspark.sql import functions as F

from lakehouse import pipeline as P
from lakehouse.generate import START, write_sources
from lakehouse.rag import REFUSAL, Assistant, evaluate

ROOT = Path(__file__).resolve().parent.parent
DAYS = 4


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    root = tmp_path_factory.mktemp("lake")
    injected = write_sources(root, days=DAYS, seed=11)
    spark = P.spark_session()
    spark.sparkContext.setLogLevel("ERROR")
    days = []
    for i in range(DAYS):
        day = str(START + dt.timedelta(days=i))
        P.bronze(spark, root / "lake", root / "landing", day)
        days.append(P.silver(spark, root / "lake", root / "landing", day))
    gold = P.gold(spark, root / "lake", root / "landing")
    return spark, root, injected, days, gold


def test_every_injected_duplicate_is_removed(lake):
    _, _, injected, days, _ = lake
    assert sum(d["duplicates_removed"] for d in days) == injected["duplicate_line"]


def test_quarantine_catches_the_injected_defects(lake):
    spark, root, injected, _, _ = lake
    q = {r["rule"]: r["count"] for r in spark.read.parquet(str(root / "lake/silver/quarantine")).groupBy("rule").count().collect()}
    assert q.get("customer_present", 0) == injected["missing_customer"]
    assert q.get("quantity_positive", 0) == injected["zero_quantity"]
    assert q.get("known_product", 0) == injected["unknown_product"]
    assert q.get("price_plausible", 0) == injected["price_in_cents"]
    assert q.get("timestamp_parsed", 0) == 0          # both date formats are parsed


def test_late_lines_land_on_their_order_day(lake):
    spark, root, _, _, _ = lake
    s = spark.read.parquet(str(root / "lake/silver/order_lines"))
    late = s.where("cast(order_date as string) != _batch_date")
    assert late.count() > 0
    assert late.where(F.datediff(F.to_date("_batch_date"), "order_date") != 1).count() == 0


def test_rerunning_a_day_changes_nothing(lake):
    spark, root, _, _, _ = lake
    path = str(root / "lake/silver/order_lines")
    before = spark.read.parquet(path).count()
    day = str(START + dt.timedelta(days=2))
    P.bronze(spark, root / "lake", root / "landing", day)
    P.silver(spark, root / "lake", root / "landing", day)
    assert spark.read.parquet(path).count() == before
    assert spark.read.parquet(path).groupBy("order_id", "line_no").count().where("count > 1").count() == 0


def test_gold_reconciles_with_silver(lake):
    assert abs(lake[4]["reconciliation"]["difference_chf"]) < 0.01


def test_no_personal_data_after_bronze(lake):
    spark, root, _, _, _ = lake
    for table in ("silver/order_lines", "gold/fact_sales", "gold/dim_customer"):
        cols = spark.read.parquet(str(root / "lake" / table)).columns
        assert "customer_email" not in cols and "customer_id" not in cols


def test_contract_lists_the_rules_the_pipeline_enforces():
    contract = yaml.safe_load((ROOT / "lakehouse/contracts.yaml").read_text())
    rules = set(contract["silver_order_lines"]["rules"])
    source = (ROOT / "lakehouse/pipeline.py").read_text()
    assert all(f'"{r}"' in source for r in rules)


def test_assistant_finds_sources_and_refuses_out_of_scope():
    r = evaluate(Assistant(), ROOT / "eval/rag_eval.json")
    assert r["hit@3"] >= 0.9 and r["refused_when_out_of_scope"] >= 0.8
    assert Assistant().answer("What is the CEO's favourite colour?")["answer"] == REFUSAL


def test_tokenizer_matches_plurals_and_keeps_column_names():
    from lakehouse.rag import tokenize
    assert tokenize("Reports categories net_amount_chf class") == ["report", "category", "net_amount_chf", "class"]
