#!/usr/bin/env python3
"""Convert candidate_data.csv to candidate_data.parquet with proper types."""

from pathlib import Path

import pandas as pd


def convert_csv_to_parquet():
    """Convert CSV to Parquet with proper data types."""

    # Get file paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    csv_file = project_root / "data" / "candidate_data.csv"
    parquet_file = project_root / "data" / "candidate_data.parquet"

    print(f"Reading CSV from: {csv_file}")

    # Read CSV
    df = pd.read_csv(csv_file)

    # Convert datetime columns
    datetime_cols = ['applied_at', 'reviewed_at', 'interviewed_at', 'offer_extended_at', 'hire_date']

    for col in datetime_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    # Ensure boolean columns are proper booleans
    bool_cols = ['offer_accepted', 'sla_met', 'reviewed', 'interviewed', 'offer_extended', 'hired']

    for col in bool_cols:
        if col in df.columns:
            # Fill NaN with False before converting to bool (NaN.astype(bool) becomes True!)
            df[col] = df[col].fillna(False).astype(bool)

    # Save as parquet
    print(f"Writing Parquet to: {parquet_file}")
    df.to_parquet(parquet_file, index=False, engine='pyarrow')

    print("✓ Conversion complete!")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {len(df.columns)}")
    print(f"  CSV size: {csv_file.stat().st_size / 1024:.1f} KB")
    print(f"  Parquet size: {parquet_file.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    convert_csv_to_parquet()
