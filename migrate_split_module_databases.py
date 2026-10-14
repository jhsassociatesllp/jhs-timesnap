"""
One-time migration: move the CV Builder, Buddy Referral and Compliance collections
out of the "Timesheets" database into their own databases.

    Timesheets.cv_profiles / cv_custom_options / cv_experience   -> CV_Builder
    Timesheets.buddy_existing_referrals / buddy_referrals /
               buddy_referral_resumes.files / .chunks (GridFS)    -> Buddy_Referral
    Timesheets.compliance_calendar_items                          -> Compliance_Table

(Mongo database names cannot contain spaces, hence the underscores.)

Run from the project root:
    python migrate_split_module_databases.py             # dry run: only reads and prints counts
    python migrate_split_module_databases.py --run        # copy (keeps the originals), then verify
    python migrate_split_module_databases.py --run --drop-source
                                                           # also drops each source collection, but ONLY
                                                           # when its copy has the same count and every _id

Safe to re-run: documents are upserted by _id, so a second --run (e.g. right after
deploying the new code) copies anything written in between. Indexes are copied too.
Order: 1) --run  2) deploy the new code  3) --run again  4) check the app  5) --drop-source
"""
import sys

from pymongo import ReplaceOne

from backend.database import _client, db

PLAN = {
    "CV_Builder": ["cv_profiles", "cv_custom_options", "cv_experience"],
    "Buddy_Referral": ["buddy_existing_referrals", "buddy_referrals",
                       "buddy_referral_resumes.files", "buddy_referral_resumes.chunks"],
    "Compliance_Table": ["compliance_calendar_items"],
}


def copy_collection(src, dst):
    ops = []
    for doc in src.find({}):
        ops.append(ReplaceOne({"_id": doc["_id"]}, doc, upsert=True))
        if len(ops) >= 200:
            dst.bulk_write(ops, ordered=False)
            ops = []
    if ops:
        dst.bulk_write(ops, ordered=False)
    for name, info in src.index_information().items():
        if name == "_id_":
            continue
        opts = {k: v for k, v in info.items() if k in ("unique", "sparse", "expireAfterSeconds")}
        dst.create_index(info["key"], name=name, **opts)


def same(src, dst):
    return (src.count_documents({}) == dst.count_documents({})
            and set(d["_id"] for d in src.find({}, {"_id": 1})) == set(d["_id"] for d in dst.find({}, {"_id": 1})))


def main():
    run, drop = "--run" in sys.argv, "--drop-source" in sys.argv
    existing = set(db.list_collection_names())
    print(("COPY + VERIFY" if run else "DRY RUN (nothing is written)") + (" + DROP SOURCE" if drop else ""))
    for dbname, colls in PLAN.items():
        for c in colls:
            if c not in existing:
                print(f"  {c:38s} not in Timesheets - skipped")
                continue
            src, dst = db[c], _client[dbname][c]
            n = src.count_documents({})
            if not run:
                print(f"  {c:38s} {n:6d} docs -> {dbname} (currently {dst.count_documents({})} there)")
                continue
            copy_collection(src, dst)
            ok = same(src, dst)
            print(f"  {c:38s} {n:6d} docs -> {dbname}: {'verified' if ok else 'MISMATCH'}")
            if drop and ok:
                src.drop()
                print(f"      dropped Timesheets.{c}")
            elif drop:
                print(f"      NOT dropped (mismatch)")


if __name__ == "__main__":
    main()
