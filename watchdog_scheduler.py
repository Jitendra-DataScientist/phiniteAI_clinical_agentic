"""
Scheduler for Supply Watchdog - Runs daily monitoring automatically.
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from watchdog_core import SupplyWatchdog
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('watchdog_scheduler.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def run_watchdog_job():
    """Execute the watchdog monitoring job."""
    logger.info("=" * 60)
    logger.info("Scheduled Watchdog Job - Starting")
    logger.info("=" * 60)

    try:
        watchdog = SupplyWatchdog()
        payload = watchdog.run()
        watchdog.close()

        # Log summary
        summary = payload['summary']
        logger.info(f"Job completed successfully:")
        logger.info(f"  Total alerts: {summary['total_alerts']}")
        logger.info(f"  Critical: {summary['critical']}")
        logger.info(f"  High: {summary['high']}")
        logger.info(f"  Medium: {summary['medium']}")

    except Exception as e:
        logger.error(f"Watchdog job failed: {e}", exc_info=True)


def start_scheduler(hour=8, minute=0):
    """
    Start the scheduler to run watchdog daily.

    Args:
        hour (int): Hour to run (0-23), default 8 AM
        minute (int): Minute to run (0-59), default 0
    """
    scheduler = BlockingScheduler()

    # Schedule daily job
    trigger = CronTrigger(hour=hour, minute=minute)
    scheduler.add_job(
        run_watchdog_job,
        trigger=trigger,
        id='daily_watchdog',
        name='Supply Watchdog Daily Monitor',
        replace_existing=True
    )

    logger.info("=" * 60)
    logger.info("Supply Watchdog Scheduler Started")
    logger.info("=" * 60)
    logger.info(f"Scheduled to run daily at {hour:02d}:{minute:02d}")
    logger.info("Press Ctrl+C to exit")
    logger.info("=" * 60)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("\nScheduler stopped by user")
        scheduler.shutdown()


if __name__ == "__main__":
    # Run immediately on start, then schedule
    logger.info("Running initial watchdog check...")
    run_watchdog_job()

    # Start scheduler for daily runs
    start_scheduler(hour=8, minute=0)  # Daily at 8:00 AM
