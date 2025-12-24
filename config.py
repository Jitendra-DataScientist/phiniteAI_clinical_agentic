"""
Configuration module for database and environment settings.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Database and application configuration."""

    # Database settings
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'clinical_supply_chain')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')

    # Data directory
    DATA_DIR = os.getenv('DATA_DIR', './synthetic_clinical_data')

    # Email settings
    SENDER_EMAIL = os.getenv('sender_email')
    APP_PASSWORD = os.getenv('app_password')
    RECIPIENT_EMAILS = os.getenv('recipient_emails')  # Comma-separated string

    @classmethod
    def get_connection_string(cls):
        """Get SQLAlchemy connection string."""
        return f"postgresql://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"

    @classmethod
    def get_psycopg2_params(cls):
        """Get psycopg2 connection parameters."""
        return {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'database': cls.DB_NAME,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD
        }

    @classmethod
    def get_recipient_list(cls):
        """Parse comma-separated recipient emails into a list."""
        if cls.RECIPIENT_EMAILS:
            return [email.strip() for email in cls.RECIPIENT_EMAILS.split(',')]
        return []
