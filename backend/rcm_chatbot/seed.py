"""
One-off seed script — loads the RCM knowledge base (ported from the
standalone Sentinel app's backend/seed_data/kb_final.json: 21 files, ~5,006
rows across categories like Trade Finance, AIF/PMS, Gift City, Swift, etc.)
into the RCM Pinecone index.

Run manually whenever data/kb_final.json changes:

    python -m backend.rcm_chatbot.seed

Idempotent: each file's namespace is fully replaced (see ingest.py), so
re-running after editing the JSON cleanly re-loads everything.
"""
import json
import os

from backend.rcm_chatbot.config import rcm_settings
from backend.rcm_chatbot.ingest import ingest_sheets, slugify

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "kb_final.json")


def seed() -> None:
    rcm_settings.validate()

    print(f"Reading {DATA_PATH} ...")
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    categories = data.get("categories", [])
    total_files = sum(len(c.get("files", [])) for c in categories)
    print(f"Found {len(categories)} categories, {total_files} files.")

    used_names = set()
    file_count = 0
    row_count = 0
    for category in categories:
        for file_entry in category.get("files", []):
            filename = file_entry["file"]
            base_name = slugify(filename)
            namespace, i = base_name, 2
            while namespace in used_names:
                namespace = f"{base_name}_{i}"
                i += 1
            used_names.add(namespace)

            sheets = file_entry.get("sheets", [])
            print(f"Ingesting '{filename}' -> namespace '{namespace}' ...")
            inserted = ingest_sheets(namespace, filename, sheets)
            print(f"  {inserted} row(s) upserted.")
            file_count += 1
            row_count += inserted

    print(f"Done. {file_count} file(s), {row_count} row(s) total across {len(used_names)} namespace(s).")


if __name__ == "__main__":
    seed()
