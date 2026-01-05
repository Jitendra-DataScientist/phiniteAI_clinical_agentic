# Supply Watchdog Usage Guide

## Overview
The Supply Watchdog is an autonomous monitoring system that detects:
1. **Expiry Alerts**: Allocated batches expiring within 90 days
2. **Shortfall Predictions**: Stock shortages within 8 weeks

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Create Database Table
```bash
python create_watchdog_table.py
```

## Usage

### Manual Run (One-Time Check)
Run the watchdog once to check current status:
```bash
python watchdog_core.py
```

This will:
- Check for expiring batches
- Analyze inventory shortfalls
- Save findings to `watchdog_findings` table
- Generate JSON output file: `watchdog_output_YYYYMMDD_HHMMSS.json`

### Scheduled Run (Daily Monitoring)
Run the watchdog automatically every day:
```bash
python watchdog_scheduler.py
```

Default schedule: Daily at 8:00 AM

To customize the schedule, edit `watchdog_scheduler.py`:
```python
start_scheduler(hour=10, minute=30)  # Run at 10:30 AM
```

The scheduler will:
- Run immediately on start
- Continue running daily at scheduled time
- Log all activity to `watchdog_scheduler.log`
- Press Ctrl+C to stop

## Output

### Database Table: `watchdog_findings`
All alerts are stored in the database with:
- Alert type and severity
- Trial, location, batch details
- Quantities and dates
- Recommended actions
- Full details in JSON format

Query recent alerts:
```sql
SELECT * FROM watchdog_findings
WHERE acknowledged = FALSE
ORDER BY severity DESC, created_at DESC;
```

### JSON Payload
Each run generates a JSON file with structure:
```json
{
  "run_id": "WD-2025-12-24-080000",
  "run_timestamp": "2025-12-24T08:00:00",
  "summary": {
    "total_alerts": 15,
    "critical": 3,
    "high": 7,
    "medium": 5
  },
  "expiry_alerts": {
    "critical": [...],
    "high": [...],
    "medium": [...]
  },
  "shortfall_predictions": {
    "critical": [...],
    "high": [...],
    "medium": [...]
  }
}
```

## Alert Severity Levels

### Expiry Alerts
- **CRITICAL**: Expires in < 30 days
- **HIGH**: Expires in < 60 days
- **MEDIUM**: Expires in < 90 days

### Shortfall Predictions
- **CRITICAL**: Stockout in < 2 weeks
- **HIGH**: Stockout in < 4 weeks
- **MEDIUM**: Stockout in < 8 weeks

## Viewing Results

### Query Active Alerts
```sql
SELECT
    alert_type,
    severity,
    trial_alias,
    location,
    batch_lot,
    recommended_action
FROM watchdog_findings
WHERE acknowledged = FALSE
ORDER BY
    CASE severity
        WHEN 'CRITICAL' THEN 1
        WHEN 'HIGH' THEN 2
        WHEN 'MEDIUM' THEN 3
    END,
    created_at DESC;
```

### Mark Alert as Acknowledged
```sql
UPDATE watchdog_findings
SET acknowledged = TRUE,
    acknowledged_by = 'your_name',
    acknowledged_at = NOW()
WHERE id = <alert_id>;
```

### View Historical Trends
```sql
SELECT
    DATE(run_timestamp) as date,
    COUNT(*) as total_alerts,
    SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) as critical_count
FROM watchdog_findings
GROUP BY DATE(run_timestamp)
ORDER BY date DESC
LIMIT 30;
```

## Production Deployment

### Option 1: Cron Job (Linux/Mac)
Add to crontab:
```bash
crontab -e
# Add line:
0 8 * * * cd /path/to/clinical_agent && /path/to/venv/bin/python watchdog_core.py
```

### Option 2: Windows Task Scheduler
1. Open Task Scheduler
2. Create new task
3. Set trigger: Daily at 8:00 AM
4. Set action: Run `python watchdog_core.py`

### Option 3: Keep Scheduler Running
Use a process manager like `systemd` or `supervisor` to keep the scheduler running:
```bash
# Run in background
nohup python watchdog_scheduler.py &
```

## Troubleshooting

**No alerts generated?**
- Check if data exists in source tables
- Verify date formats in CSV data
- Check database connection in `.env`

**Scheduler not running?**
- Check `watchdog_scheduler.log` for errors
- Verify APScheduler is installed
- Ensure database is accessible

**Consumption rate seems wrong?**
- Default is 2 packages per patient visit
- Adjust in `watchdog_core.py` line ~127
- Add actual BOM data for accurate calculation
