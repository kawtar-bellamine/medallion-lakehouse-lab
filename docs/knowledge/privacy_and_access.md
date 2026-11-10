# Personal data and access

Bronze keeps the files as received, including customer emails, and is readable only by the data engineering team.
Retention of Bronze is 90 days. Silver and Gold contain no direct personal data: the customer id is replaced by a
SHA-256 key and the email column is dropped. Analysts and Power BI users only read Gold.

The Swiss Federal Act on Data Protection (nFADP) and the GDPR for European web customers apply. A request to delete
a customer is handled by removing the customer from the ERP and replaying Bronze; the hashed key then disappears from
Silver and Gold at the next rebuild.

Access is granted by role: data engineers (Bronze, Silver, Gold), analysts (Gold), business users (Power BI reports).
On Databricks the roles map to Unity Catalog groups with grants on the bronze, silver and gold schemas.
