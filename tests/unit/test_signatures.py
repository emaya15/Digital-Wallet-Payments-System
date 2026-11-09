import hashlib
import hmac

from app.utils.signatures import (
    razorpay_payment_signature,
    verify_razorpay_payment_signature,
    verify_webhook_signature,
    webhook_signature,
)

SECRET = "test_secret_value"


def test_payment_signature_matches_reference_hmac():
    expected = hmac.new(SECRET.encode(), b"order_ABC|pay_XYZ", hashlib.sha256).hexdigest()
    assert razorpay_payment_signature("order_ABC", "pay_XYZ", SECRET) == expected


def test_payment_signature_verification():
    sig = razorpay_payment_signature("order_ABC", "pay_XYZ", SECRET)
    assert verify_razorpay_payment_signature("order_ABC", "pay_XYZ", sig, SECRET)
    assert not verify_razorpay_payment_signature("order_ABC", "pay_OTHER", sig, SECRET)
    assert not verify_razorpay_payment_signature("order_ABC", "pay_XYZ", sig, "wrong_secret")
    assert not verify_razorpay_payment_signature("order_ABC", "pay_XYZ", "", SECRET)
    assert not verify_razorpay_payment_signature("order_ABC", "pay_XYZ", sig, "")


def test_webhook_signature_verification():
    body = b'{"event":"payment.captured"}'
    sig = webhook_signature(body, SECRET)
    assert verify_webhook_signature(body, sig, SECRET)
    assert not verify_webhook_signature(body + b" ", sig, SECRET)
    assert not verify_webhook_signature(body, "deadbeef", SECRET)
    assert not verify_webhook_signature(body, sig, "")
