"""Global configuration for the Travel Planner application.

This module loads environment variables from .env file and provides
centralized configuration for the entire application.
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Load environment variables from .env file
# Look for .env in the project root directory
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)


# ============================================================================
# Language Model Configuration
# ============================================================================

# Default model name for Gemini
DEFAULT_MODEL_NAME: str = os.getenv("DEFAULT_MODEL_NAME", "gemini-3-flash-preview")

# Default temperature for LLM calls
DEFAULT_TEMPERATURE: float = float(os.getenv("DEFAULT_TEMPERATURE", "0.2"))

# Model name for car price agent (uses gemini-2.0-flash-exp)
CAR_PRICE_MODEL_NAME: str = os.getenv("CAR_PRICE_MODEL_NAME", "gemini-3-flash-preview")


# ============================================================================
# Agent Configuration
# ============================================================================

# Budget Agent defaults
BUDGET_DEFAULT_HOTEL_RATE: float = float(os.getenv("BUDGET_DEFAULT_HOTEL_RATE", "180.0"))
BUDGET_DINING_PER_PERSON: float = float(os.getenv("BUDGET_DINING_PER_PERSON", "35.0"))
BUDGET_ACTIVITY_PER_STOP: float = float(os.getenv("BUDGET_ACTIVITY_PER_STOP", "40.0"))
BUDGET_FUEL_EFFICIENCY_MPG: float = float(os.getenv("BUDGET_FUEL_EFFICIENCY_MPG", "26.0"))

# Itinerary Agent defaults
ITINERARY_DEFAULT_BLOCKS_PER_DAY: int = int(os.getenv("ITINERARY_DEFAULT_BLOCKS_PER_DAY", "3"))

# Research Agent defaults
RESEARCH_MAX_CONCURRENCY: int = int(os.getenv("RESEARCH_MAX_CONCURRENCY", "5"))


# ============================================================================
# Application Configuration
# ============================================================================

# FastAPI/Backend
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
TRAVEL_PLANNER_API_URL: str = os.getenv("TRAVEL_PLANNER_API_URL", "http://localhost:8000")

# CORS Configuration
CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", "*").split(",") if os.getenv("CORS_ORIGINS") else ["*"]


# ============================================================================
# Session Storage Configuration
# ============================================================================

# Redis connection URL (e.g., redis://localhost:6379/0 or redis://:password@host:port/0)
REDIS_URL: Optional[str] = os.getenv("REDIS_URL")

# Session TTL in seconds (default: 24 hours)
SESSION_TTL_SECONDS: int = int(os.getenv("SESSION_TTL_SECONDS", "86400"))


# ============================================================================
# AWS Configuration
# ============================================================================

# AWS Region
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

# AWS Secrets Manager secret name (optional, for storing API keys)
AWS_SECRETS_MANAGER_SECRET_NAME: Optional[str] = os.getenv("AWS_SECRETS_MANAGER_SECRET_NAME")


# ============================================================================
# AWS Secrets Manager Integration
# ============================================================================

def _get_secret_from_aws(secret_name: str, region: str = AWS_REGION) -> Optional[dict]:
    """Fetch secret from AWS Secrets Manager."""
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        import json

        return json.loads(response["SecretString"])
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.warning("boto3 not installed. Cannot fetch secrets from AWS Secrets Manager.")
        return None
    except ClientError as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to fetch secret from AWS Secrets Manager: {e}")
        return None
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Error fetching secret from AWS: {e}")
        return None


def _get_api_key_with_fallback(env_var: str, secret_key: Optional[str] = None) -> Optional[str]:
    """Get API key from environment variable or AWS Secrets Manager."""
    # First try environment variable
    value = os.getenv(env_var)
    if value:
        return value

    # Then try AWS Secrets Manager if configured
    if AWS_SECRETS_MANAGER_SECRET_NAME and secret_key:
        secrets = _get_secret_from_aws(AWS_SECRETS_MANAGER_SECRET_NAME)
        if secrets and secret_key in secrets:
            return secrets[secret_key]

    return None


# ============================================================================
# API Keys (with AWS Secrets Manager support)
# ============================================================================

def get_google_api_key() -> Optional[str]:
    """Get Google API key (Gemini) - checks AWS Secrets Manager, then environment variables."""
    return (
        _get_api_key_with_fallback("GOOGLE_API_KEY", "GOOGLE_API_KEY")
        or _get_api_key_with_fallback("GEMINI_API_KEY", "GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )


def get_google_maps_api_key() -> Optional[str]:
    """Get Google Maps API key - checks AWS Secrets Manager, then environment variables."""
    return (
        _get_api_key_with_fallback("GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_API_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
    )


def get_amadeus_api_key() -> Optional[str]:
    """Get Amadeus API key - checks AWS Secrets Manager, then environment variables."""
    return (
        _get_api_key_with_fallback("AMADEUS_API_KEY", "AMADEUS_API_KEY")
        or os.getenv("AMADEUS_API_KEY")
    )


def get_amadeus_api_secret() -> Optional[str]:
    """Get Amadeus API secret - checks AWS Secrets Manager, then environment variables."""
    return (
        _get_api_key_with_fallback("AMADEUS_API_SECRET", "AMADEUS_API_SECRET")
        or os.getenv("AMADEUS_API_SECRET")
    )


# ============================================================================
# Validation
# ============================================================================

def validate_api_keys() -> List[str]:
    """Validate that required API keys are present. Returns list of missing keys."""
    missing = []
    
    if not get_google_maps_api_key():
        missing.append("GOOGLE_MAPS_API_KEY")
    
    if not get_google_api_key():
        missing.append("GOOGLE_API_KEY or GEMINI_API_KEY")
    
    if not get_amadeus_api_key() or not get_amadeus_api_secret():
        missing.append("AMADEUS_API_KEY/AMADEUS_API_SECRET")
    
    return missing

