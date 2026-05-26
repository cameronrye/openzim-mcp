"""Validate probe set meets per-class minimum coverage (Criterion F)."""

import json
from collections import Counter
from pathlib import Path

REQUIRED_CLASSES = {
    "Z1",
    "Z2",
    "Z3",
    "Z4",
    "OPP-1",
    "Sub-pattern-C",
    "filler-prose",
    "possessive",
    "zim_get-toc",
    "zim_get-summary",
    "zim_get-structure",
    "zim_get-binary",
    "zim_get-main-page",
    "zim_get-batch",
    "zim_browse-page",
    "zim_browse-walk",
    "zim_metadata",
    "zim_links-outbound",
    "zim_links-related",
    "zim_health",
}

MIN_PER_CLASS = 20


def main():
    probes_path = Path(__file__).resolve().parent / "probes.jsonl"
    probes = [
        json.loads(line)
        for line in probes_path.read_text().splitlines()
        if line.strip()
    ]
    counts: Counter = Counter()
    z4_zim_query_preferred = 0
    for p in probes:
        for cls in p["operational_classes"]:
            counts[cls] += 1
        if (
            "Z4" in p["operational_classes"]
            and p["tool_eligibility"] == "zim_query_preferred"
        ):
            z4_zim_query_preferred += 1

    failures = []
    for cls in REQUIRED_CLASSES:
        if counts[cls] < MIN_PER_CLASS:
            failures.append(f"{cls}: {counts[cls]} (need {MIN_PER_CLASS})")
    if z4_zim_query_preferred < 20:
        failures.append(
            f"Z4 zim_query_preferred: {z4_zim_query_preferred} (need 20 for Criterion C3)"
        )

    if failures:
        print("PROBE COVERAGE FAILURE:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print(
        f"OK: {len(probes)} probes, all {len(REQUIRED_CLASSES)} classes meet "
        f">={MIN_PER_CLASS} threshold."
    )
    print(
        f"OK: {z4_zim_query_preferred} Z4 zim_query_preferred probes for Criterion C3."
    )


if __name__ == "__main__":
    main()
