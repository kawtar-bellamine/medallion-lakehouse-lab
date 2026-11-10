"""Architecture and star-schema diagrams (Graphviz), drawn from code so they stay in sync with the pipeline."""
from __future__ import annotations

import subprocess
from pathlib import Path

FONT = "Helvetica"
LAYER = {"landing": ("#f1efe9", "#6b6862"), "bronze": ("#f6e3d3", "#9a5a2b"), "silver": ("#e7eaee", "#5b6470"),
         "gold": ("#f8edc8", "#9a7a10"), "serve": ("#e3eefb", "#2a5fa8")}


def _card(title, rows, layer, width=190):
    bg, ink = LAYER[layer]
    body = "".join(f'<TR><TD ALIGN="LEFT" BALIGN="LEFT"><FONT POINT-SIZE="10" COLOR="#3a3935">{r}</FONT></TD></TR>'
                   for r in rows)
    return (f'<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="5" BGCOLOR="{bg}" STYLE="ROUNDED" '
            f'WIDTH="{width}"><TR><TD ALIGN="LEFT"><B><FONT POINT-SIZE="12" COLOR="{ink}">{title}</FONT></B></TD></TR>'
            f'{body}</TABLE>>')


def architecture() -> str:
    n = {
        "erp": _card("ERP orders", ["daily CSV, 5 channels", "CHF and EUR, 2 date formats"], "landing"),
        "web": _card("Web analytics", ["daily JSON lines", "page views to checkout"], "landing"),
        "ref": _card("Product catalogue", ["120 products, FR and DE"], "landing"),
        "bronze": _card("BRONZE", ["files as received, all text", "+ source file, ingestion time", "partition: batch date"], "bronze"),
        "silver": _card("SILVER", ["typed, deduplicated, CHF", "customer id hashed (SHA-256)", "5 contract rules",
                                   "partition: business date"], "silver"),
        "quar": _card("QUARANTINE", ["rejected lines + rule name", "reviewed by the data steward"], "silver", 170),
        "gold": _card("GOLD", ["fact_sales + 4 dimensions", "4 KPI tables", "reconciled with Silver"], "gold"),
        "pbi": _card("Power BI", ["star schema, 11 DAX measures"], "serve", 170),
        "app": _card("Streamlit app", ["KPIs, quality, lineage"], "serve", 170),
        "rag": _card("RAG assistant", ["docs + data dictionary", "cites sources, refuses"], "serve", 170),
    }
    lines = ['digraph G {', 'rankdir=LR; bgcolor="transparent"; nodesep=0.25; ranksep=0.55; pad=0.2;',
             f'node [shape=plain fontname="{FONT}"]; edge [color="#9a9893" arrowsize=0.7 penwidth=1.4 '
             f'fontname="{FONT}" fontsize=9 fontcolor="#52514e"];']
    lines += [f"{k} [label={v}];" for k, v in n.items()]
    lines += ['{rank=same; erp; web; ref}', '{rank=same; pbi; app; rag}',
              'erp -> bronze; web -> bronze; ref -> silver [style=dashed label="lookup"];',
              'bronze -> silver [label=" contracts "]; silver -> quar [color="#c2410c" label=" rule broken "];',
              'silver -> gold [label=" star schema "]; gold -> pbi; gold -> app; gold -> rag [style=dashed];', "}"]
    return "\n".join(lines)


def star() -> str:
    def table(name, cols, layer, key_cols=()):
        bg, ink = LAYER[layer]
        rows = "".join(f'<TR><TD ALIGN="LEFT" PORT="{c}"><FONT POINT-SIZE="10" COLOR="{"#0b0b0b" if c in key_cols else "#52514e"}">'
                       f'{"&#9679; " if c in key_cols else ""}{c}</FONT></TD></TR>' for c in cols)
        return (f'{name} [label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" BGCOLOR="{bg}" '
                f'STYLE="ROUNDED"><TR><TD ALIGN="LEFT"><B><FONT POINT-SIZE="12" COLOR="{ink}">{name}</FONT></B></TD></TR>'
                f'{rows}</TABLE>>];')
    lines = ['graph G {', 'layout=neato; overlap=false; bgcolor="transparent"; pad=0.2; splines=true;',
             f'node [shape=plain fontname="{FONT}"]; edge [color="#c9a227" penwidth=1.6];',
             table("fact_sales", ["date_key", "order_id", "line_no", "channel", "customer_key", "product_code",
                                  "quantity", "status", "amount_chf", "net_amount_chf"], "gold",
                   ("date_key", "channel", "customer_key", "product_code")) + ' fact_sales [pos="0,0!"];',
             table("dim_date", ["date_key", "date", "weekday", "iso_week", "month"], "silver", ("date_key",))
             + ' dim_date [pos="-3.2,1.4!"];',
             table("dim_channel", ["channel", "channel_type", "market"], "silver", ("channel",))
             + ' dim_channel [pos="-3.2,-1.5!"];',
             table("dim_product", ["product_code", "category", "name_fr", "name_de", "list_price_chf", "launch_year"],
                   "silver", ("product_code",)) + ' dim_product [pos="3.3,1.3!"];',
             table("dim_customer", ["customer_key", "first_order_date", "orders", "main_channel"], "silver",
                   ("customer_key",)) + ' dim_customer [pos="3.3,-1.5!"];',
             "fact_sales -- dim_date; fact_sales -- dim_channel; fact_sales -- dim_product; fact_sales -- dim_customer;",
             "}"]
    return "\n".join(lines)


def render(root: Path):
    out = root / "docs" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    for name, src in (("architecture", architecture()), ("star_schema", star())):
        subprocess.run(["dot", "-Tpng", "-Gdpi=170", "-o", str(out / f"{name}.png")], input=src.encode(), check=True)


if __name__ == "__main__":
    render(Path(__file__).resolve().parent.parent)
