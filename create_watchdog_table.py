"""
Create the watchdog_findings table for storing Supply Watchdog alerts.
"""
from sqlalchemy import create_engine, URL, text
from config import Config

def create_watchdog_table():
    """Create the watchdog_findings table in the database."""

    # Connect to database
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        database=Config.DB_NAME,
    )
    engine = create_engine(url)

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS watchdog_findings (
        id SERIAL PRIMARY KEY,
        run_timestamp TIMESTAMP DEFAULT NOW(),
        alert_type VARCHAR(50) NOT NULL,
        severity VARCHAR(20),
        trial_alias VARCHAR(100),
        location VARCHAR(200),
        batch_lot VARCHAR(100),
        material_description VARCHAR(500),
        expiry_date DATE,
        days_until_expiry INT,
        current_quantity DECIMAL,
        projected_shortage_date DATE,
        weekly_consumption_rate DECIMAL,
        weeks_until_stockout DECIMAL,
        details JSONB,
        recommended_action TEXT,
        email_sent BOOLEAN DEFAULT FALSE,
        acknowledged BOOLEAN DEFAULT FALSE,
        acknowledged_by VARCHAR(100),
        acknowledged_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_run_timestamp ON watchdog_findings(run_timestamp);
    CREATE INDEX IF NOT EXISTS idx_alert_type ON watchdog_findings(alert_type);
    CREATE INDEX IF NOT EXISTS idx_severity ON watchdog_findings(severity);
    CREATE INDEX IF NOT EXISTS idx_trial ON watchdog_findings(trial_alias);
    CREATE INDEX IF NOT EXISTS idx_acknowledged ON watchdog_findings(acknowledged);
    """

    try:
        with engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()
            print("✓ watchdog_findings table created successfully")

            # Verify table was created
            result = conn.execute(text("""
                SELECT COUNT(*) as count
                FROM information_schema.tables
                WHERE table_name = 'watchdog_findings'
            """))
            count = result.fetchone()[0]

            if count > 0:
                print("✓ Table verified in database")
            else:
                print("✗ Table creation may have failed")

    except Exception as e:
        print(f"✗ Error creating table: {e}")
    finally:
        engine.dispose()

if __name__ == "__main__":
    print("Creating watchdog_findings table...")
    print("=" * 60)
    create_watchdog_table()
