"""WS /ws/wallet - live balance and payment notifications for the authenticated user only."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.auth.dependencies import user_from_token
from app.database import SessionLocal
from app.services.wallet_service import get_wallet_for_user
from app.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])

POLICY_VIOLATION = 1008


def _authenticate(token: str) -> Optional[tuple]:
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        wallet = get_wallet_for_user(db, user.id)
        return user.id, str(wallet.balance)
    except HTTPException:
        return None
    finally:
        db.close()


@router.websocket("/ws/wallet")
async def wallet_socket(websocket: WebSocket, token: Optional[str] = Query(None)):
    """Authenticate with ``?token=<JWT>`` or an ``Authorization: Bearer <JWT>`` header.

    Events pushed: connected, balance_update, payment_sent, payment_received,
    merchant_payment, withdrawal_update, money_request, payment_on_hold, ...
    Send the text ``ping`` to receive ``{"event": "pong"}``.
    """
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    identity = await run_in_threadpool(_authenticate, token) if token else None
    if identity is None:
        await websocket.close(code=POLICY_VIOLATION)
        return
    user_id, balance = identity
    await manager.connect(user_id, websocket)
    try:
        await websocket.send_json({"event": "connected", "balance": balance})
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info("WebSocket for user %s closed unexpectedly", user_id)
    finally:
        manager.disconnect(user_id, websocket)
