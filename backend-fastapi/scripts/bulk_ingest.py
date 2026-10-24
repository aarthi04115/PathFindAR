#!/usr/bin/env python3
"""
Bulk Reference Frame Ingestion CLI

Reads a CSV file mapping image filenames to their known 6-DoF poses
and ingests all of them into the reference frame database.

CSV format:
  filename,floor,pos_x,pos_y,pos_z,rot_x,rot_y,rot_z,rot_w
  hallway_001.jpg,0,1.5,0.0,3.2,0.0,0.0,0.0,1.0
  hallway_002.jpg,0,2.0,0.0,3.2,0.0,0.1,0.0,0.995

Usage:
  python scripts/bulk_ingest.py \\
    --image-dir ./data/mapping_walk/ \\
    --csv ./data/mapping_walk/poses.csv \\
    --db ./data/reference_frames.db

  # Or generate a sample CSV template:
  python scripts/bulk_ingest.py --generate-template ./data/sample_poses.csv
"""

import argparse
import csv
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.localization.storage import ReferenceFrameStore
from app.localization.ingestion import IngestionEngine


def generate_template(output_path: str) -> None:
    """Write a sample CSV template showing the expected format."""
    rows = [
        ["filename", "floor", "pos_x", "pos_y", "pos_z", "rot_x", "rot_y", "rot_z", "rot_w"],
        ["hallway_001.jpg", "0", "1.5", "0.0", "3.2", "0.0", "0.0", "0.0", "1.0"],
        ["hallway_002.jpg", "0", "2.0", "0.0", "3.2", "0.0", "0.1", "0.0", "0.995"],
        ["stairwell_001.jpg", "0", "5.0", "0.0", "8.0", "0.0", "0.707", "0.0", "0.707"],
        ["room201_001.jpg", "1", "3.0", "4.0", "2.0", "0.0", "0.0", "0.0", "1.0"],
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"✅ Template CSV written to: {output_path}")
    print(f"   Edit the file with your actual image names and poses,")
    print(f"   then run: python scripts/bulk_ingest.py --image-dir <folder> --csv {output_path}")


def bulk_ingest(image_dir: str, csv_path: str, db_path: str) -> None:
    """Read CSV, ingest each image into the reference database."""
    image_dir = Path(image_dir)
    if not image_dir.is_dir():
        print(f"❌ Image directory not found: {image_dir}")
        sys.exit(1)

    csv_path_obj = Path(csv_path)
    if not csv_path_obj.exists():
        print(f"❌ CSV file not found: {csv_path}")
        sys.exit(1)

    # Initialize storage + engine
    store = ReferenceFrameStore(db_path)
    engine = IngestionEngine(
        store=store,
        image_dir=Path(db_path).parent / "reference_images",
        feature_dir=Path(db_path).parent / "reference_features",
    )

    # Read CSV
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("❌ CSV is empty (no data rows found)")
        sys.exit(1)

    print(f"📂 Image directory : {image_dir}")
    print(f"📄 CSV file        : {csv_path} ({len(rows)} entries)")
    print(f"💾 Database        : {db_path}")
    print(f"{'─' * 60}")

    success = 0
    failed = 0
    t0 = time.perf_counter()

    for i, row in enumerate(rows, 1):
        filename = row["filename"].strip()
        image_path = image_dir / filename

        if not image_path.exists():
            print(f"  ⚠️  [{i}/{len(rows)}] Skip — file not found: {filename}")
            failed += 1
            continue

        # Check if already ingested
        existing = store.get_by_filename(filename)
        if existing:
            print(f"  ⏭️  [{i}/{len(rows)}] Skip — already ingested: {filename}")
            continue

        try:
            position = [float(row["pos_x"]), float(row["pos_y"]), float(row["pos_z"])]
            rotation = [
                float(row.get("rot_x", 0)),
                float(row.get("rot_y", 0)),
                float(row.get("rot_z", 0)),
                float(row.get("rot_w", 1)),
            ]
            floor = int(row.get("floor", 0))

            frame = engine.ingest_file(
                image_path=image_path,
                position=position,
                rotation=rotation,
                floor=floor,
            )
            print(f"  ✅ [{i}/{len(rows)}] #{frame.id} {filename} → floor={floor} pos={position}")
            success += 1

        except Exception as exc:
            print(f"  ❌ [{i}/{len(rows)}] Error ingesting {filename}: {exc}")
            failed += 1

    elapsed = time.perf_counter() - t0
    print(f"{'─' * 60}")
    print(f"Done in {elapsed:.1f}s — {success} ingested, {failed} failed")
    print(f"Total frames in database: {store.count()}")
    store.close()


def main():
    parser = argparse.ArgumentParser(
        description="Bulk ingest reference frames from a folder + CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--image-dir", type=str,
        help="Directory containing the reference images",
    )
    parser.add_argument(
        "--csv", type=str,
        help="CSV file mapping filenames to poses",
    )
    parser.add_argument(
        "--db", type=str, default="./data/reference_frames.db",
        help="Path to SQLite database (default: ./data/reference_frames.db)",
    )
    parser.add_argument(
        "--generate-template", type=str, metavar="OUTPUT_PATH",
        help="Generate a sample CSV template and exit",
    )

    args = parser.parse_args()

    if args.generate_template:
        generate_template(args.generate_template)
        return

    if not args.image_dir or not args.csv:
        parser.error("Both --image-dir and --csv are required (or use --generate-template)")

    bulk_ingest(args.image_dir, args.csv, args.db)


if __name__ == "__main__":
    main()
