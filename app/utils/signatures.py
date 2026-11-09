"""HMAC SHA256 helpers for Razorpay payment confirmation and webhooks."""
import hashlib
import hmac


def _hexdigest(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def razorpay_payment_signature(order_id: str, payment_id: str, secret: str) -> str:
    """Signature Razorpay Checkout returns: HMAC_SHA256(order_id|payment_id)."""
    return _hexdigest(secret, f"{order_id}|{payment_id}".encode("utf-8"))


def verify_razorpay_payment_signature(order_id: str, payment_id: str, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = razorpay_payment_signature(order_id, payment_id, secret)
    return hmac.compare_digest(expected, signature)


def webhook_signature(body: bytes, secret: str) -> str:
    return _hexdigest(secret, body)


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    return hmac.compare_digest(webhook_signature(body, secret), signature)
