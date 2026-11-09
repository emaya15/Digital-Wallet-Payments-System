"""Global test configuration.

Environment variables are set BEFORE the application is imported so that the
engine points at the separate TEST database and heavy production settings
(bcrypt cost, scheduler) are relaxed. The test database is never the dev DB.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["APP_ENV"] = "test"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["STATEMENTS_DIR"] = os.path.join(os.path.dirname(__file__), "_statements_tmp")
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_dummy")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "dummy_key_secret_for_tests")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret_for_tests")

_test_url = os.environ.get("TEST_DATABASE_URL")
if _test_url is None:
    try:  # fall back to the value in .env.example style files
        from dotenv import dotenv_values

        _test_url = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env")).get("TEST_DATABASE_URL")
    except Exception:  # pragma: no cover
        _test_url = None
os.environ["DATABASE_URL"] = _test_url or "mysql+pymysql://wallet_user:wallet_password@localhost:3306/digital_wallet_test"
