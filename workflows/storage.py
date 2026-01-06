"""Redis-based session storage for Travel Planner."""

from __future__ import annotations

import json
import logging
from typing import Optional

import redis
from redis.exceptions import ConnectionError, RedisError

from config import REDIS_URL, SESSION_TTL_SECONDS
from workflows.state import TravelPlannerState

logger = logging.getLogger(__name__)


class SessionStorage:
    """Redis-based session storage with fallback to in-memory storage."""

    def __init__(self) -> None:
        self._redis_client: Optional[redis.Redis] = None
        self._fallback_storage: dict[str, TravelPlannerState] = {}
        self._use_redis = False

        if REDIS_URL:
            try:
                self._redis_client = redis.from_url(
                    REDIS_URL,
                    decode_responses=False,  # We'll handle JSON encoding/decoding ourselves
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    health_check_interval=30,
                )
                # Test connection
                self._redis_client.ping()
                self._use_redis = True
                logger.info("Connected to Redis for session storage")
            except (ConnectionError, RedisError, Exception) as e:
                logger.warning(f"Failed to connect to Redis: {e}. Using in-memory storage.")
                self._redis_client = None
                self._use_redis = False
        else:
            logger.info("REDIS_URL not set. Using in-memory storage.")

    def get(self, session_id: str) -> Optional[TravelPlannerState]:
        """Retrieve a session by ID."""
        if self._use_redis and self._redis_client:
            try:
                data = self._redis_client.get(f"session:{session_id}")
                if data:
                    state_dict = json.loads(data)
                    return TravelPlannerState.model_validate(state_dict)
            except (RedisError, json.JSONDecodeError, Exception) as e:
                logger.error(f"Error retrieving session {session_id} from Redis: {e}")
                return None
        else:
            return self._fallback_storage.get(session_id)

    def set(self, session_id: str, state: TravelPlannerState) -> None:
        """Store a session with TTL."""
        if self._use_redis and self._redis_client:
            try:
                state_dict = state.model_dump()
                data = json.dumps(state_dict, default=str)  # default=str handles datetime serialization
                self._redis_client.setex(
                    f"session:{session_id}",
                    SESSION_TTL_SECONDS,
                    data,
                )
            except (RedisError, Exception) as e:
                logger.error(f"Error storing session {session_id} in Redis: {e}")
                # Fallback to in-memory
                self._fallback_storage[session_id] = state
        else:
            self._fallback_storage[session_id] = state

    def delete(self, session_id: str) -> None:
        """Delete a session."""
        if self._use_redis and self._redis_client:
            try:
                self._redis_client.delete(f"session:{session_id}")
            except RedisError as e:
                logger.error(f"Error deleting session {session_id} from Redis: {e}")
        else:
            self._fallback_storage.pop(session_id, None)

    def exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        if self._use_redis and self._redis_client:
            try:
                return bool(self._redis_client.exists(f"session:{session_id}"))
            except RedisError as e:
                logger.error(f"Error checking session {session_id} in Redis: {e}")
                return False
        else:
            return session_id in self._fallback_storage


# Global session storage instance
_session_storage: Optional[SessionStorage] = None


def get_session_storage() -> SessionStorage:
    """Get or create the global session storage instance."""
    global _session_storage
    if _session_storage is None:
        _session_storage = SessionStorage()
    return _session_storage

