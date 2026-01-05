# Clinical Supply Chain Data Loader

This project loads clinical trial supply chain data from CSV files into a PostgreSQL database.

## Project Structure

```
clinical_agent/
├── .env                          # Environment variables (database credentials)
├── .gitignore                    # Git ignore file
├── config.py                     # Configuration module
├── db_loader.py                  # Database loader class
├── load_data.py                  # Main script to load data
├── requirements.txt              # Python dependencies
├── synthetic_clinical_data/      # CSV data files (40 files)
└── README.md                     # This file
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Database

The `.env` file contains your database credentials:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=clinical_supply_chain
DB_USER=postgres
DB_PASSWORD=SUBzero@156
DATA_DIR=./synthetic_clinical_data
```

### 3. Create Database

Make sure PostgreSQL is running and create the database:

```bash
createdb clinical_supply_chain
```

Or using psql:

```sql
CREATE DATABASE clinical_supply_chain;
```

## Usage

### Load All Data

Run the main script to load all CSV files:

```bash
python load_data.py
```

This will:
- Connect to PostgreSQL
- Load all 40 CSV files from `synthetic_clinical_data/`
- Create tables automatically
- Show progress and summary

### Output Example

```
==============================================================
Clinical Supply Chain Data Loader
==============================================================
✓ Connected to database: clinical_supply_chain

Loading CSV files from: ./synthetic_clinical_data
==============================================================
  ✓ Loaded affiliate_warehouse_inventory: 150 rows
  ✓ Loaded allocated_materials_to_orders: 500 rows
  ✓ Loaded available_inventory_report: 300 rows
  ...
==============================================================

📊 Loading Summary:
  Total files: 40
  Successfully loaded: 40
  Failed: 0
  Total rows loaded: 15000

📋 Loaded Tables:
==============================================================
  affiliate_warehouse_inventory: 150 rows
  allocated_materials_to_orders: 500 rows
  ...
```

## Modules

### `config.py`
- Loads environment variables from `.env`
- Provides database configuration
- Generates connection strings

### `db_loader.py`
- `DatabaseLoader` class handles all data loading
- `connect()`: Establishes database connection
- `load_csv_to_table()`: Loads single CSV file
- `load_all_csvs()`: Loads all CSV files from directory
- `verify_tables()`: Verifies loaded tables and row counts

### `load_data.py`
- Main entry point
- Orchestrates the loading process
- Provides user-friendly output

## Table Naming Convention

CSV filenames are converted to table names:
- Hyphens replaced with underscores
- `re-evaluation.csv` → `re_evaluation`
- `batch_master.csv` → `batch_master`

## Data Overview

The database contains 40 tables covering:
- **Inventory**: batch_master, available_inventory_report, warehouse inventories
- **Demand**: enrollment_rate_report, patient_status_and_treatment_report
- **Manufacturing**: manufacturing_orders, planned_orders, bom_details
- **Logistics**: distribution_order_report, shipment tracking
- **Quality/Regulatory**: inspection_lot, qdocs, rim, re_evaluation

## Next Steps

After loading data, you may want to:

1. **Add indexes** for better query performance
2. **Define primary keys** and **foreign keys**
3. **Convert data types** (dates, numbers) from TEXT
4. **Build the AI agent** system for supply chain monitoring

## Troubleshooting

### Connection Failed
- Ensure PostgreSQL is running
- Verify credentials in `.env`
- Check database exists: `psql -l`

### Permission Denied
- Ensure user has CREATE TABLE permissions
- Grant privileges: `GRANT ALL ON DATABASE clinical_supply_chain TO postgres;`

### Data Loading Errors
- Check CSV file encoding (should be UTF-8)
- Verify CSV files are in `synthetic_clinical_data/` directory
