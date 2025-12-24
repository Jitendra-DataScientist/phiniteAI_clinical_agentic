"""
Database loader module for loading CSV files into PostgreSQL.
"""
import os
import pandas as pd
from sqlalchemy import create_engine, URL
from sqlalchemy.exc import SQLAlchemyError
from config import Config


class DatabaseLoader:
    """Handle loading CSV files into PostgreSQL database."""

    def __init__(self):
        """Initialize database connection."""
        self.config = Config()
        self.engine = None
        self.connection_string = Config.get_connection_string()

    def connect(self):
        try:
            # Use SQLAlchemy URL.create() to properly handle special characters in password
            url = URL.create(
                drivername="postgresql+psycopg2",
                username=self.config.DB_USER,
                password=self.config.DB_PASSWORD,
                host=self.config.DB_HOST,
                port=int(self.config.DB_PORT),
                database=self.config.DB_NAME,
            )
            self.engine = create_engine(url)
            self.connection = self.engine.connect()
            print("✓ Database connection successful")
            return True
        except Exception as e:
            print(f"✗ Database connection failed: {e}")
            return False

    def load_csv_to_table(self, csv_file_path, table_name, if_exists='replace', chunksize=1000):
        """
        Load a single CSV file into a PostgreSQL table.

        Args:
            csv_file_path (str): Path to CSV file
            table_name (str): Name of the table to create
            if_exists (str): How to behave if table exists ('replace', 'append', 'fail')
            chunksize (int): Number of rows to insert at a time

        Returns:
            int: Number of rows loaded, or -1 on failure
        """
        try:
            # Read CSV file
            df = pd.read_csv(csv_file_path)

            # Load into database
            df.to_sql(
                table_name,
                self.engine,
                if_exists=if_exists,
                index=False,
                method='multi',
                chunksize=chunksize
            )

            row_count = len(df)
            print(f"  ✓ Loaded {table_name}: {row_count} rows")
            return row_count

        except Exception as e:
            print(f"  ✗ Failed to load {table_name}: {e}")
            return -1

    def load_all_csvs(self, data_dir=None):
        """
        Load all CSV files from the data directory.

        Args:
            data_dir (str): Directory containing CSV files. Uses Config.DATA_DIR if None.

        Returns:
            dict: Summary of loading results
        """
        if data_dir is None:
            data_dir = Config.DATA_DIR

        if not os.path.exists(data_dir):
            print(f"✗ Data directory not found: {data_dir}")
            return None

        print(f"\nLoading CSV files from: {data_dir}")
        print("=" * 60)

        csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv')]

        if not csv_files:
            print(f"✗ No CSV files found in {data_dir}")
            return None

        results = {
            'total_files': len(csv_files),
            'loaded': 0,
            'failed': 0,
            'total_rows': 0,
            'tables': []
        }

        for filename in sorted(csv_files):
            # Convert filename to table name (replace hyphens with underscores)
            table_name = filename.replace('.csv', '').replace('-', '_')
            file_path = os.path.join(data_dir, filename)

            row_count = self.load_csv_to_table(file_path, table_name)

            if row_count >= 0:
                results['loaded'] += 1
                results['total_rows'] += row_count
                results['tables'].append(table_name)
            else:
                results['failed'] += 1

        print("=" * 60)
        print(f"\n📊 Loading Summary:")
        print(f"  Total files: {results['total_files']}")
        print(f"  Successfully loaded: {results['loaded']}")
        print(f"  Failed: {results['failed']}")
        print(f"  Total rows loaded: {results['total_rows']}")

        return results

    def verify_tables(self):
        """Verify loaded tables and show row counts."""
        try:
            query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """

            with self.engine.connect() as conn:
                tables = pd.read_sql(query, conn)

            if tables.empty:
                print("\n✗ No tables found in database")
                return

            print("\n📋 Loaded Tables:")
            print("=" * 60)

            for table in tables['table_name']:
                count_query = f"SELECT COUNT(*) as count FROM {table}"
                with self.engine.connect() as conn:
                    result = pd.read_sql(count_query, conn)
                    count = result['count'][0]
                    print(f"  {table}: {count} rows")

        except Exception as e:
            print(f"✗ Failed to verify tables: {e}")

    def close(self):
        """Close database connection."""
        if self.engine:
            self.engine.dispose()
            print("\n✓ Database connection closed")
