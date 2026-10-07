import os
import tempfile
from pathlib import Path

# Never use the upstream database or real email/Redis in tests.
_test_dir = tempfile.TemporaryDirectory()
settings = {
    'DATABASE_URL': 'sqlite+aiosqlite:///' + str(Path(_test_dir.name) / 'test.sqlite3'),
    'SECRET_KEY': 'test-only-email-key', 'JWT_SECRET': 'test-only-jwt-key',
    'JWT_ALGORITHM': 'HS256', 'JTI_EXPIRY': '86400', 'ACCESS_TOKEN_EXPIRY': '3600',
    'REFRESH_TOKEN_EXPIRY': '1', 'REDIS_HOST': '127.0.0.1', 'REDIS_PORT': '6379',
    'DOMAIN': 'http://testserver', 'MAIL_USERNAME': '', 'MAIL_PASSWORD': '',
    'MAIL_FROM': 'test@example.com', 'MAIL_PORT': '1025', 'MAIL_SERVER': 'localhost',
    'MAIL_FROM_NAME': 'Tawseela Test', 'MAIL_STARTTLS': 'false', 'MAIL_SSL_TLS': 'false',
    'USE_CREDENTIALS': 'false', 'VALIDATE_CERTS': 'true',
}
os.environ.update(settings)
