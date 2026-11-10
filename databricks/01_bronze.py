# Databricks notebook source
# MAGIC %md Bronze step of the daily medallion job. Same code as the local run (lakehouse/pipeline.py).

# COMMAND ----------
from pathlib import Path
from lakehouse import pipeline as P

LANDING = Path("/Volumes/alpina/raw/landing")
LAKE = Path("/Volumes/alpina/lake/files")

# COMMAND ----------
print(P.bronze(spark, LAKE, LANDING, dbutils.widgets.get("day")))
