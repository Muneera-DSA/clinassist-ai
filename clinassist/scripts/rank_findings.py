from . import script

LEVEL = {"high": 0, "review": 1, "info": 2}


@script("rank_findings", kind="aggregate", needs_record=False,
        does="Collect the findings from every check script already run in this request into one list, sorted by the level "
             "each rule assigns and then by the newest evidence date. It does not run any check itself.",
        returns="all findings gathered so far, sorted, with the script that produced each",
        tags=["aggregate", "rank", "sort", "summary", "priority", "all findings"])
def run(ctx):
    rows = []
    for key, out in ctx.gathered.items():
        if isinstance(out, dict) and "findings" in out:
            for f in out["findings"]:
                rows.append({**f, "from_script": key.split("(")[0]})
    rows.sort(key=lambda f: (LEVEL.get(f.get("rule_level"), 3), f.get("title", "")))
    return {"n": len(rows), "findings": rows, "scripts_included": sorted({r["from_script"] for r in rows})}
