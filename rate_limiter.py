from flask import request, jsonify
from functools import wraps
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = {}  # {ip: [timestamps]}
    
    def is_allowed(self, identifier, limit_per_minute=5, limit_per_hour=50):
        """Check if request is allowed based on rate limits"""
        current_time = datetime.now()
        
        if identifier not in self.requests:
            self.requests[identifier] = []
        
        # Clean up old requests
        minute_ago = current_time - timedelta(minutes=1)
        hour_ago = current_time - timedelta(hours=1)
        
        self.requests[identifier] = [
            req_time for req_time in self.requests[identifier] 
            if req_time > hour_ago
        ]
        
        # Count recent requests
        minute_requests = sum(1 for req_time in self.requests[identifier] if req_time > minute_ago)
        hour_requests = len(self.requests[identifier])
        
        # Check limits
        if minute_requests >= limit_per_minute:
            logger.warning(f"Rate limit exceeded (minute) for {identifier}: {minute_requests}/{limit_per_minute}")
            return False, f"Rate limit exceeded: {limit_per_minute} requests per minute"
        
        if hour_requests >= limit_per_hour:
            logger.warning(f"Rate limit exceeded (hour) for {identifier}: {hour_requests}/{limit_per_hour}")
            return False, f"Rate limit exceeded: {limit_per_hour} requests per hour"
        
        # Add current request
        self.requests[identifier].append(current_time)
        return True, None
    
    def rate_limit(self, per_minute=5, per_hour=50):
        """Decorator for rate limiting endpoints"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                # Use IP address as identifier
                identifier = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ['REMOTE_ADDR'])
                
                allowed, error_message = self.is_allowed(identifier, per_minute, per_hour)
                
                if not allowed:
                    return jsonify({
                        "error": error_message,
                        "retry_after": "60 seconds"
                    }), 429
                
                return f(*args, **kwargs)
            return decorated_function
        return decorator

# Global rate limiter instance
rate_limiter = RateLimiter()
