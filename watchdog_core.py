"""
Supply Watchdog - Core detection logic for expiry alerts and shortfall predictions.
"""
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import create_engine, URL, text
from config import Config
import json
import threading
from mail_sender_util import send_gmail_html_multi


class SupplyWatchdog:
    """Main class for Supply Watchdog autonomous monitoring."""

    def __init__(self):
        """Initialize database connection."""
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            database=Config.DB_NAME,
        )
        self.engine = create_engine(url)

    def detect_expiry_alerts(self):
        """
        Detect allocated batches expiring within 90 days.
        Returns list of alerts categorized by severity.
        """
        query = """
        SELECT
            a.material_component_batch as batch_lot,
            a.trial_alias,
            a.material_description,
            i.expiration_date as expiry_date,
            i.warehouse_name as location,
            CAST(i.actual_qty AS NUMERIC) as quantity,
            a.order_id,
            a.order_status
        FROM allocated_materials_to_orders a
        JOIN complete_warehouse_inventory i
            ON a.material_component_batch = i.lot_number
        WHERE a.order_status IN ('Released', 'In Progress', 'Created')
        """

        try:
            df = pd.read_sql(query, self.engine)

            # Convert expiry_date to datetime
            df['expiry_date'] = pd.to_datetime(df['expiry_date'], errors='coerce')

            # Calculate days until expiry
            today = pd.Timestamp.now()
            df['days_until_expiry'] = (df['expiry_date'] - today).dt.days

            # Filter: expiring within 90 days
            expiring = df[df['days_until_expiry'] <= 90].copy()

            # Categorize by severity
            expiring.loc[:, 'severity'] = 'MEDIUM'
            expiring.loc[expiring['days_until_expiry'] < 60, 'severity'] = 'HIGH'
            expiring.loc[expiring['days_until_expiry'] < 30, 'severity'] = 'CRITICAL'

            alerts = []
            for _, row in expiring.iterrows():
                alert = {
                    'alert_type': 'EXPIRY_ALERT',
                    'severity': row['severity'],
                    'trial_alias': row['trial_alias'],
                    'location': row['location'],
                    'batch_lot': row['batch_lot'],
                    'material_description': row['material_description'],
                    'expiry_date': row['expiry_date'].date() if pd.notna(row['expiry_date']) else None,
                    'days_until_expiry': int(row['days_until_expiry']) if pd.notna(row['days_until_expiry']) else None,
                    'current_quantity': float(row['quantity']) if pd.notna(row['quantity']) else 0,
                    'details': {
                        'order_id': row['order_id'],
                        'order_status': row['order_status']
                    }
                }

                # Generate recommendation
                if row['severity'] == 'CRITICAL':
                    alert['recommended_action'] = f"URGENT: Expedite shipment or reallocate batch {row['batch_lot']} immediately - expires in {int(row['days_until_expiry'])} days"
                elif row['severity'] == 'HIGH':
                    alert['recommended_action'] = f"Plan shipment for batch {row['batch_lot']} within 2 weeks - expires in {int(row['days_until_expiry'])} days"
                else:
                    alert['recommended_action'] = f"Monitor batch {row['batch_lot']} - expires in {int(row['days_until_expiry'])} days"

                alerts.append(alert)

            print(f"[OK] Detected {len(alerts)} expiry alerts")
            return alerts

        except Exception as e:
            print(f"[ERROR] Error detecting expiry alerts: {e}")
            return []

    def detect_shortfall_predictions(self):
        """
        Detect potential stock shortfalls within 8 weeks.
        Compares projected demand against current inventory.
        """
        # Step 1: Calculate consumption rate from patient visits
        consumption_query = """
        SELECT
            "Trial Alias" as trial_alias,
            COUNT(DISTINCT patient) as total_patients,
            COUNT(*) as total_visits,
            COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT
                TO_CHAR(TO_DATE(visit_date, 'YYYY-MM-DD'), 'YYYY-MM')
            ), 0) as visits_per_month
        FROM patient_status_and_treatment_report
        WHERE TO_DATE(visit_date, 'YYYY-MM-DD') >= CURRENT_DATE - INTERVAL '3 months'
        GROUP BY "Trial Alias"
        """

        # Step 2: Get current inventory
        inventory_query = """
        SELECT
            trial_alias,
            warehouse_name as location,
            description as material,
            SUM(CAST(actual_qty AS NUMERIC)) as total_stock
        FROM complete_warehouse_inventory
        GROUP BY trial_alias, warehouse_name, description
        HAVING SUM(CAST(actual_qty AS NUMERIC)) > 0
        """

        try:
            consumption_df = pd.read_sql(consumption_query, self.engine)
            inventory_df = pd.read_sql(inventory_query, self.engine)

            # Assume 2 packages per visit (conservative estimate)
            consumption_df['packages_per_month'] = consumption_df['visits_per_month'] * 2
            consumption_df['packages_per_week'] = consumption_df['packages_per_month'] / 4.33

            # Merge inventory with consumption
            merged = inventory_df.merge(consumption_df, on='trial_alias', how='left')

            # Fill missing consumption with conservative default (10 packages/week)
            merged['packages_per_week'].fillna(10, inplace=True)

            # Calculate weeks until stockout
            merged['weeks_until_stockout'] = merged['total_stock'] / merged['packages_per_week']

            # Filter: stockout within 8 weeks
            shortfalls = merged[merged['weeks_until_stockout'] < 8].copy()

            # Categorize severity
            shortfalls.loc[:, 'severity'] = 'MEDIUM'
            shortfalls.loc[shortfalls['weeks_until_stockout'] < 4, 'severity'] = 'HIGH'
            shortfalls.loc[shortfalls['weeks_until_stockout'] < 2, 'severity'] = 'CRITICAL'

            alerts = []
            for _, row in shortfalls.iterrows():
                shortage_date = datetime.now() + timedelta(weeks=row['weeks_until_stockout'])

                alert = {
                    'alert_type': 'SHORTFALL_PREDICTION',
                    'severity': row['severity'],
                    'trial_alias': row['trial_alias'],
                    'location': row['location'],
                    'material_description': row['material'],
                    'current_quantity': float(row['total_stock']),
                    'weekly_consumption_rate': float(row['packages_per_week']),
                    'weeks_until_stockout': float(row['weeks_until_stockout']),
                    'projected_shortage_date': shortage_date.date(),
                    'details': {
                        'total_patients': int(row['total_patients']) if pd.notna(row['total_patients']) else None,
                        'visits_per_month': float(row['visits_per_month']) if pd.notna(row['visits_per_month']) else None
                    }
                }

                # Generate recommendation
                weeks = row['weeks_until_stockout']
                if row['severity'] == 'CRITICAL':
                    alert['recommended_action'] = f"URGENT: Initiate emergency order for {row['trial_alias']} at {row['location']} - stockout in {weeks:.1f} weeks"
                elif row['severity'] == 'HIGH':
                    alert['recommended_action'] = f"Expedite regular order for {row['trial_alias']} at {row['location']} - stockout in {weeks:.1f} weeks"
                else:
                    alert['recommended_action'] = f"Plan replenishment for {row['trial_alias']} at {row['location']} - stockout in {weeks:.1f} weeks"

                alerts.append(alert)

            print(f"✓ Detected {len(alerts)} shortfall predictions")
            return alerts

        except Exception as e:
            print(f"✗ Error detecting shortfall predictions: {e}")
            return []

    def save_findings(self, alerts):
        """Save alerts to watchdog_findings table."""
        if not alerts:
            print("No alerts to save")
            return 0

        run_timestamp = datetime.now()
        saved_count = 0

        try:
            with self.engine.connect() as conn:
                for alert in alerts:
                    insert_query = text("""
                        INSERT INTO watchdog_findings (
                            run_timestamp, alert_type, severity, trial_alias, location,
                            batch_lot, material_description, expiry_date, days_until_expiry,
                            current_quantity, projected_shortage_date, weekly_consumption_rate,
                            weeks_until_stockout, details, recommended_action
                        ) VALUES (
                            :run_timestamp, :alert_type, :severity, :trial_alias, :location,
                            :batch_lot, :material_description, :expiry_date, :days_until_expiry,
                            :current_quantity, :projected_shortage_date, :weekly_consumption_rate,
                            :weeks_until_stockout, :details, :recommended_action
                        )
                    """)

                    conn.execute(insert_query, {
                        'run_timestamp': run_timestamp,
                        'alert_type': alert.get('alert_type'),
                        'severity': alert.get('severity'),
                        'trial_alias': alert.get('trial_alias'),
                        'location': alert.get('location'),
                        'batch_lot': alert.get('batch_lot'),
                        'material_description': alert.get('material_description'),
                        'expiry_date': alert.get('expiry_date'),
                        'days_until_expiry': alert.get('days_until_expiry'),
                        'current_quantity': alert.get('current_quantity'),
                        'projected_shortage_date': alert.get('projected_shortage_date'),
                        'weekly_consumption_rate': alert.get('weekly_consumption_rate'),
                        'weeks_until_stockout': alert.get('weeks_until_stockout'),
                        'details': json.dumps(alert.get('details', {})),
                        'recommended_action': alert.get('recommended_action')
                    })
                    saved_count += 1

                conn.commit()

            print(f"✓ Saved {saved_count} alerts to database")
            return saved_count

        except Exception as e:
            print(f"✗ Error saving findings: {e}")
            return 0

    def generate_json_payload(self, alerts):
        """Generate JSON payload for email system."""
        run_id = f"WD-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"

        # Categorize alerts
        expiry_critical = [a for a in alerts if a['alert_type'] == 'EXPIRY_ALERT' and a['severity'] == 'CRITICAL']
        expiry_high = [a for a in alerts if a['alert_type'] == 'EXPIRY_ALERT' and a['severity'] == 'HIGH']
        expiry_medium = [a for a in alerts if a['alert_type'] == 'EXPIRY_ALERT' and a['severity'] == 'MEDIUM']

        shortfall_critical = [a for a in alerts if a['alert_type'] == 'SHORTFALL_PREDICTION' and a['severity'] == 'CRITICAL']
        shortfall_high = [a for a in alerts if a['alert_type'] == 'SHORTFALL_PREDICTION' and a['severity'] == 'HIGH']
        shortfall_medium = [a for a in alerts if a['alert_type'] == 'SHORTFALL_PREDICTION' and a['severity'] == 'MEDIUM']

        total_critical = len(expiry_critical) + len(shortfall_critical)
        total_high = len(expiry_high) + len(shortfall_high)
        total_medium = len(expiry_medium) + len(shortfall_medium)

        # Convert date objects to strings for JSON serialization
        def serialize_alert(alert):
            serialized = alert.copy()
            if 'expiry_date' in serialized and serialized['expiry_date']:
                serialized['expiry_date'] = serialized['expiry_date'].isoformat()
            if 'projected_shortage_date' in serialized and serialized['projected_shortage_date']:
                serialized['projected_shortage_date'] = serialized['projected_shortage_date'].isoformat()
            return serialized

        payload = {
            "run_id": run_id,
            "run_timestamp": datetime.now().isoformat(),
            "summary": {
                "total_alerts": len(alerts),
                "critical": total_critical,
                "high": total_high,
                "medium": total_medium
            },
            "expiry_alerts": {
                "critical": [serialize_alert(a) for a in expiry_critical],
                "high": [serialize_alert(a) for a in expiry_high],
                "medium": [serialize_alert(a) for a in expiry_medium]
            },
            "shortfall_predictions": {
                "critical": [serialize_alert(a) for a in shortfall_critical],
                "high": [serialize_alert(a) for a in shortfall_high],
                "medium": [serialize_alert(a) for a in shortfall_medium]
            }
        }

        return payload

    def generate_html_email(self, payload):
        """Generate HTML email content from watchdog payload."""
        run_id = payload['run_id']
        run_timestamp = payload['run_timestamp']
        summary = payload['summary']
        expiry_alerts = payload['expiry_alerts']
        shortfall_predictions = payload['shortfall_predictions']

        # Color scheme
        colors = {
            'CRITICAL': {'bg': '#ffcccc', 'text': '#cc0000'},
            'HIGH': {'bg': '#ffe6cc', 'text': '#ff6600'},
            'MEDIUM': {'bg': '#fff9cc', 'text': '#cc9900'}
        }

        # Start HTML
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #555; margin-top: 30px; }}
                .summary-box {{
                    background-color: #f2f2f2;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                    font-size: 14px;
                }}
                th {{
                    background-color: #f2f2f2;
                    border: 1px solid #ddd;
                    padding: 10px;
                    text-align: left;
                }}
                td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                    color: #666;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <h1>Supply Watchdog Alert Report</h1>
            <p><strong>Run ID:</strong> {run_id}</p>
            <p><strong>Timestamp:</strong> {run_timestamp}</p>

            <div class="summary-box">
                <h3>Summary</h3>
                <p><strong>Total Alerts: {summary['total_alerts']}</strong></p>
                <p style="color: {colors['CRITICAL']['text']};">CRITICAL: {summary['critical']}</p>
                <p style="color: {colors['HIGH']['text']};">HIGH: {summary['high']}</p>
                <p style="color: {colors['MEDIUM']['text']};">MEDIUM: {summary['medium']}</p>
            </div>
        """

        # Check if there are any alerts
        if summary['total_alerts'] == 0:
            html += """
            <p>All systems normal. No expiry or shortfall alerts detected.</p>
            """
        else:
            # Expiry Alerts Section
            total_expiry = len(expiry_alerts['critical']) + len(expiry_alerts['high']) + len(expiry_alerts['medium'])
            if total_expiry > 0:
                html += """
                <h2>🔴 Expiring Batches</h2>
                <table>
                    <tr>
                        <th>Severity</th>
                        <th>Trial</th>
                        <th>Location</th>
                        <th>Batch Lot</th>
                        <th>Material</th>
                        <th>Expiry Date</th>
                        <th>Days Left</th>
                        <th>Quantity</th>
                        <th>Action</th>
                    </tr>
                """

                # Add alerts by severity
                for severity in ['critical', 'high', 'medium']:
                    for alert in expiry_alerts[severity]:
                        bg_color = colors[severity.upper()]['bg']
                        text_color = colors[severity.upper()]['text']
                        html += f"""
                    <tr style="background-color: {bg_color};">
                        <td style="color: {text_color}; font-weight: bold;">{alert['severity']}</td>
                        <td>{alert['trial_alias']}</td>
                        <td>{alert['location']}</td>
                        <td>{alert['batch_lot']}</td>
                        <td>{alert['material_description']}</td>
                        <td>{alert['expiry_date']}</td>
                        <td>{alert['days_until_expiry']}</td>
                        <td>{alert['current_quantity']}</td>
                        <td>{alert['recommended_action']}</td>
                    </tr>
                        """

                html += """
                </table>
                """

            # Shortfall Predictions Section
            total_shortfall = len(shortfall_predictions['critical']) + len(shortfall_predictions['high']) + len(shortfall_predictions['medium'])
            if total_shortfall > 0:
                html += """
                <h2>📉 Stock Shortfall Predictions</h2>
                <table>
                    <tr>
                        <th>Severity</th>
                        <th>Trial</th>
                        <th>Location</th>
                        <th>Material</th>
                        <th>Current Stock</th>
                        <th>Weekly Usage</th>
                        <th>Weeks Left</th>
                        <th>Stockout Date</th>
                        <th>Action</th>
                    </tr>
                """

                # Add alerts by severity
                for severity in ['critical', 'high', 'medium']:
                    for alert in shortfall_predictions[severity]:
                        bg_color = colors[severity.upper()]['bg']
                        text_color = colors[severity.upper()]['text']
                        html += f"""
                    <tr style="background-color: {bg_color};">
                        <td style="color: {text_color}; font-weight: bold;">{alert['severity']}</td>
                        <td>{alert['trial_alias']}</td>
                        <td>{alert['location']}</td>
                        <td>{alert['material_description']}</td>
                        <td>{alert['current_quantity']:.1f}</td>
                        <td>{alert['weekly_consumption_rate']:.2f}</td>
                        <td>{alert['weeks_until_stockout']:.1f}</td>
                        <td>{alert['projected_shortage_date']}</td>
                        <td>{alert['recommended_action']}</td>
                    </tr>
                        """

                html += """
                </table>
                """

        # Footer
        html += f"""
            <div class="footer">
                <p>This is an automated alert from Supply Watchdog</p>
                <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>Check database for full details</p>
            </div>
        </body>
        </html>
        """

        return html

    def _send_email_thread(self, payload):
        """
        Thread target function to send email alerts.
        This runs in a separate thread to avoid blocking the main process.

        Args:
            payload: The JSON payload with all alerts
        """
        try:
            # Generate dynamic subject line
            summary = payload['summary']
            if summary['total_alerts'] == 0:
                subject = "Supply Watchdog: No alerts detected"
            else:
                subject = f"Supply Watchdog Alert: {summary['critical']} CRITICAL, {summary['high']} HIGH, {summary['medium']} MEDIUM"

            # Generate HTML body
            html_body = self.generate_html_email(payload)

            # Load email configuration
            sender_email = Config.SENDER_EMAIL
            app_password = Config.APP_PASSWORD
            recipient_list = Config.get_recipient_list()

            if not sender_email or not app_password or not recipient_list:
                print("✗ Email configuration missing. Please check .env file.")
                return

            # Send email with retry logic
            success = send_gmail_html_multi(
                sender_email=sender_email,
                app_password=app_password,
                recipient_list=recipient_list,
                subject=subject,
                html_body=html_body
            )

            if success:
                print("✓ Email alerts sent successfully")
            else:
                print("✗ Failed to send email after all retry attempts")

        except Exception as e:
            print(f"✗ Unexpected error in email thread: {e}")

    def send_email_alerts(self, payload):
        """
        Launch email sending in a separate thread.

        Args:
            payload: The JSON payload with all alerts
        """
        email_thread = threading.Thread(target=self._send_email_thread, args=(payload,))
        email_thread.start()

    def run(self):
        """Execute the watchdog monitoring cycle."""
        print("\n" + "=" * 60)
        print("Supply Watchdog - Starting Monitoring Cycle")
        print("=" * 60)

        # Detect expiry alerts
        print("\n1. Checking for expiring batches...")
        expiry_alerts = self.detect_expiry_alerts()

        # Detect shortfall predictions
        print("\n2. Analyzing inventory shortfall predictions...")
        shortfall_alerts = self.detect_shortfall_predictions()

        # Combine all alerts
        all_alerts = expiry_alerts + shortfall_alerts

        print(f"\n3. Total alerts detected: {len(all_alerts)}")

        # Save to database
        print("\n4. Saving findings to database...")
        self.save_findings(all_alerts)

        # Generate JSON payload
        print("\n5. Generating JSON payload...")
        payload = self.generate_json_payload(all_alerts)

        # Save JSON to file
        print("\n6. Saving JSON payload...")
        output_file = f"watchdog_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(payload, f, indent=2)

        print(f"✓ JSON payload saved to: {output_file}")

        # Send email alerts in background
        print("\n7. Sending email alerts in background...")
        self.send_email_alerts(payload)
        print("✓ Email thread started (sending in background)")

        print("\n" + "=" * 60)
        print("Supply Watchdog - Monitoring Cycle Complete")
        print("=" * 60)

        return payload

    def close(self):
        """Close database connection."""
        if self.engine:
            self.engine.dispose()


if __name__ == "__main__":
    watchdog = SupplyWatchdog()
    try:
        watchdog.run()
    finally:
        watchdog.close()
