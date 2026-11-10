# Pipeline operations

The pipeline runs once a day at 06:00 after the ERP and web files have landed. Steps: Bronze ingestion, Silver
validation and merge, Gold rebuild, reconciliation. On Databricks it is a job with three tasks defined in
databricks/job.yml; locally it is python run.py.

Reruns are safe: every step overwrites only the partitions of the day it processes, so replaying a day gives the
same tables. The reconciliation step compares completed revenue in Silver with revenue in Gold; the run fails if the
difference exceeds one franc.

If a source file is missing, the Bronze task fails and the day is not processed; the next run catches up.
Owners: ERP team for order files, Digital team for web events, data engineering for the pipeline.
