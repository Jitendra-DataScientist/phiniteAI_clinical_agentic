"""
Main script to load clinical supply chain data into PostgreSQL.
"""
import sys
from db_loader import DatabaseLoader


def main():
    """Main function to execute data loading."""
    print("=" * 60)
    print("Clinical Supply Chain Data Loader")
    print("=" * 60)

    # Initialize loader
    loader = DatabaseLoader()

    # Connect to database
    if not loader.connect():
        print("\n✗ Exiting due to connection failure")
        sys.exit(1)

    # Load all CSV files
    results = loader.load_all_csvs()

    if results is None:
        print("\n✗ Data loading failed")
        loader.close()
        sys.exit(1)

    # Verify loaded tables
    loader.verify_tables()

    # Close connection
    loader.close()

    print("\n✓ Data loading complete!")

    if results['failed'] > 0:
        sys.exit(1)

    return 0


if __name__ == "__main__":
    main()
