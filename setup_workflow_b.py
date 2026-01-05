"""
Setup database tables and indexes for Workflow B: Scenario Strategist
"""
from sqlalchemy import create_engine, URL, text
from config import Config
import sys


def create_tables(engine):
    """Create all required tables."""
    print("\n1. Creating tables...")

    with engine.connect() as conn:
        # Table metadata catalog
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS table_metadata (
                table_name TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                key_columns TEXT[] NOT NULL,
                business_purpose TEXT NOT NULL,
                typical_queries TEXT[],
                related_tables TEXT[],
                sample_row_count INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        print("   ✓ table_metadata created")

        # Value index for fuzzy matching
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS table_value_index (
                id SERIAL PRIMARY KEY,
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                distinct_values TEXT[] NOT NULL,
                value_count INTEGER,
                sample_size INTEGER DEFAULT 1000,
                last_updated TIMESTAMP DEFAULT NOW()
            )
        """))
        print("   ✓ table_value_index created")

        # Chat sessions
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                created_at TIMESTAMP DEFAULT NOW(),
                last_activity TIMESTAMP DEFAULT NOW(),
                conversation_history JSONB DEFAULT '[]'::jsonb,
                user_context JSONB DEFAULT '{}'::jsonb,
                user_metadata JSONB DEFAULT '{}'::jsonb,
                total_messages INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE
            )
        """))
        print("   ✓ chat_sessions created")

        conn.commit()


def create_indexes(engine):
    """Create indexes for performance."""
    print("\n2. Creating indexes...")

    with engine.connect() as conn:
        # Metadata indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_metadata_category
            ON table_metadata(category)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_metadata_purpose
            ON table_metadata USING gin(to_tsvector('english', business_purpose))
        """))

        # Value index indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_value_index_table_column
            ON table_value_index(table_name, column_name)
        """))

        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_value_index_unique
            ON table_value_index(table_name, column_name)
        """))

        # Session indexes
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_activity
            ON chat_sessions(last_activity)
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_active
            ON chat_sessions(is_active) WHERE is_active = TRUE
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_session_context
            ON chat_sessions USING gin(user_context)
        """))

        conn.commit()
        print("   ✓ All indexes created")


def enable_extensions(engine):
    """Enable PostgreSQL extensions."""
    print("\n3. Enabling extensions...")

    with engine.connect() as conn:
        # pg_trgm for fuzzy matching
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        print("   ✓ pg_trgm enabled")

        conn.commit()


def create_fuzzy_indexes(engine):
    """Create trigram indexes for fuzzy matching."""
    print("\n4. Creating fuzzy match indexes...")

    with engine.connect() as conn:
        # Trial alias
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_trial_alias_trgm
            ON batch_master USING gin("Trial Alias" gin_trgm_ops)
        """))

        # Batch number
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_batch_number_trgm
            ON batch_master USING gin("Batch number" gin_trgm_ops)
        """))

        # LY Number
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_ly_number_trgm
            ON re_evaluation USING gin("LY Number (Molecule Planner to Complete)" gin_trgm_ops)
        """))

        # Country
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_country_trgm
            ON ip_shipping_timelines_report USING gin(country_name gin_trgm_ops)
        """))

        # Material
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_material_trgm
            ON batch_master USING gin("Material" gin_trgm_ops)
        """))

        conn.commit()
        print("   ✓ All fuzzy match indexes created")


def populate_metadata(engine):
    """Populate table_metadata with key tables."""
    print("\n5. Populating table metadata...")

    metadata_entries = [
        {
            'table': 're_evaluation',
            'category': 'regulatory',
            'description': 'Re-evaluation history for extending batch shelf life. Tracks requests, statuses, and outcomes.',
            'key_columns': ['ID', 'Lot Number (Molecule Planner to Complete)', 'Request Type (Molecule Planner to Complete)', 'Sample Status (NDP Material Coordinator to Complete)', 'LY Number (Molecule Planner to Complete)'],
            'purpose': 'Check if a specific batch has been previously re-evaluated for shelf-life extension. Determine re-evaluation history and current status.',
            'typical_queries': ['Has batch X been re-evaluated?', 'What is the re-evaluation status for LY123?', 'Show all pending re-evaluations'],
            'related_tables': ['batch_master', 'qdocs']
        },
        {
            'table': 'rim',
            'category': 'regulatory',
            'description': 'Regulatory Information Management - tracks regulatory submissions to health authorities by country.',
            'key_columns': ['name_v', 'health_authority_division_c', 'type_v', 'status_v', 'approved_date_c', 'clinical_study_v', 'ly_number_c', 'submission_outcome'],
            'purpose': 'Verify if regulatory approval exists for shelf-life extension in a specific country. Track submission status across health authorities.',
            'typical_queries': ['Is extension approved in Germany?', 'What is the regulatory status for LY123 in FDA?', 'Show all approved submissions for Trial ABC'],
            'related_tables': ['material_country_requirements']
        },
        {
            'table': 'ip_shipping_timelines_report',
            'category': 'logistics',
            'description': 'Shipping timelines from warehouse to sites by country. Critical for calculating lead times.',
            'key_columns': ['ip_helper', 'ip_timeline', 'country_name'],
            'purpose': 'Determine if there is sufficient time to execute shelf-life extension given shipping timelines. Calculate total lead time including re-evaluation processing.',
            'typical_queries': ['How long does shipping to Germany take?', 'What is the timeline for country X?'],
            'related_tables': ['warehouse_and_site_shipment_tracking_report', 'distribution_order_report']
        },
        {
            'table': 'batch_master',
            'category': 'inventory',
            'description': 'Master data for all batches including expiry dates, manufacturing dates, and stock levels.',
            'key_columns': ['Batch number', 'Material', 'Trial Alias', 'Expiration date_shelf life', 'Expiry Extension Date', 'Total Stock'],
            'purpose': 'Core batch information. Used to lookup batch details, current expiry status, stock levels, and trial associations.',
            'typical_queries': ['Show details for batch X', 'What is the expiry date of batch Y?', 'List all batches for Trial ABC'],
            'related_tables': ['allocated_materials_to_orders', 'complete_warehouse_inventory']
        },
        {
            'table': 'allocated_materials_to_orders',
            'category': 'logistics',
            'description': 'Materials and batches allocated to manufacturing/packaging orders. Links batches to production.',
            'key_columns': ['order_id', 'material_component_batch', 'trial_alias', 'order_status', 'ly_number'],
            'purpose': 'Track which batches are allocated to which orders. Determine order status and allocation history.',
            'typical_queries': ['Which orders use batch X?', 'Show allocations for Trial ABC'],
            'related_tables': ['batch_master', 'manufacturing_orders']
        },
        {
            'table': 'material_country_requirements',
            'category': 'regulatory',
            'description': 'Material approval requirements by country. Tracks which materials are approved in which countries.',
            'key_columns': ['Trial Alias', 'Countries', 'Material Number'],
            'purpose': 'Verify country-specific material requirements and approvals. Used in conjunction with RIM for regulatory checks.',
            'typical_queries': ['Is material X approved in Germany?', 'Show all materials for Trial ABC in USA'],
            'related_tables': ['rim', 'batch_master']
        },
    ]

    with engine.connect() as conn:
        for entry in metadata_entries:
            conn.execute(text("""
                INSERT INTO table_metadata (
                    table_name, category, description, key_columns,
                    business_purpose, typical_queries, related_tables
                )
                VALUES (
                    :table, :category, :description, :key_columns,
                    :purpose, :typical_queries, :related_tables
                )
                ON CONFLICT (table_name) DO UPDATE SET
                    category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    key_columns = EXCLUDED.key_columns,
                    business_purpose = EXCLUDED.business_purpose,
                    typical_queries = EXCLUDED.typical_queries,
                    related_tables = EXCLUDED.related_tables,
                    updated_at = NOW()
            """), entry)

        conn.commit()
        print(f"   ✓ Populated {len(metadata_entries)} key tables")
        print(f"   ⚠ Note: Remaining tables should be added manually or via script")


def populate_value_index(engine):
    """Populate value index for fuzzy matching."""
    print("\n6. Populating value index...")

    with engine.connect() as conn:
        # Trial aliases
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'batch_master',
                'Trial Alias',
                ARRAY_AGG(DISTINCT "Trial Alias" ORDER BY "Trial Alias"),
                COUNT(DISTINCT "Trial Alias")
            FROM batch_master
            WHERE "Trial Alias" IS NOT NULL
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} trial aliases")

        # Batch numbers (sample 1000)
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'batch_master',
                'Batch number',
                ARRAY_AGG("Batch number" ORDER BY "Batch number"),
                (SELECT COUNT(DISTINCT "Batch number") FROM batch_master)
            FROM (
                SELECT DISTINCT "Batch number"
                FROM batch_master
                WHERE "Batch number" IS NOT NULL
                LIMIT 1000
            ) sub
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} batch numbers (sample)")

        # Countries
        result = conn.execute(text("""
            INSERT INTO table_value_index (table_name, column_name, distinct_values, value_count)
            SELECT
                'ip_shipping_timelines_report',
                'country_name',
                ARRAY_AGG(DISTINCT country_name ORDER BY country_name),
                COUNT(DISTINCT country_name)
            FROM ip_shipping_timelines_report
            WHERE country_name IS NOT NULL
            ON CONFLICT (table_name, column_name)
            DO UPDATE SET
                distinct_values = EXCLUDED.distinct_values,
                value_count = EXCLUDED.value_count,
                last_updated = NOW()
            RETURNING value_count
        """))
        count = result.fetchone()[0]
        print(f"   ✓ Indexed {count} countries")

        conn.commit()


def create_cleanup_function(engine):
    """Create session cleanup function."""
    print("\n7. Creating cleanup function...")

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION cleanup_old_sessions()
            RETURNS INTEGER AS $$
            DECLARE
                deleted_count INTEGER;
            BEGIN
                DELETE FROM chat_sessions
                WHERE last_activity < NOW() - INTERVAL '24 hours'
                AND is_active = FALSE;

                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                RETURN deleted_count;
            END;
            $$ LANGUAGE plpgsql;
        """))

        conn.commit()
        print("   ✓ Cleanup function created")


def test_fuzzy_matching(engine):
    """Test fuzzy matching functionality."""
    print("\n8. Testing fuzzy matching...")

    with engine.connect() as conn:
        # Test trial alias matching
        result = conn.execute(text("""
            SELECT
                "Trial Alias",
                similarity("Trial Alias", 'Trial ABC') as score
            FROM batch_master
            WHERE "Trial Alias" % 'Trial ABC'
            ORDER BY score DESC
            LIMIT 3
        """))

        matches = result.fetchall()
        if matches:
            print("   ✓ Fuzzy matching working:")
            for match in matches:
                print(f"      - {match[0]} (score: {match[1]:.2f})")
        else:
            print("   ⚠ No fuzzy matches found (this might be normal if no similar data exists)")


def main():
    """Main setup function."""
    print("=" * 60)
    print("WORKFLOW B: DATABASE SETUP")
    print("=" * 60)

    # Create engine
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=Config.DB_USER,
        password=Config.DB_PASSWORD,
        host=Config.DB_HOST,
        port=int(Config.DB_PORT),
        database=Config.DB_NAME,
    )

    try:
        engine = create_engine(url)

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"\n✓ Connected to PostgreSQL")
            print(f"  Version: {version.split(',')[0]}")

        # Run setup steps
        create_tables(engine)
        create_indexes(engine)
        enable_extensions(engine)
        create_fuzzy_indexes(engine)
        populate_metadata(engine)
        populate_value_index(engine)
        create_cleanup_function(engine)
        test_fuzzy_matching(engine)

        print("\n" + "=" * 60)
        print("✓ SETUP COMPLETE")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start n8n: docker run -p 5678:5678 docker.n8n.io/n8nio/n8n")
        print("2. Import n8n workflow")
        print("3. Start Gradio UI: python gradio_chat_ui.py")
        print("\n" + "=" * 60)

        engine.dispose()
        return 0

    except Exception as e:
        print(f"\n✗ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
