from fastapi import APIRouter

router = APIRouter()

@router.get("/saldos/{telegram_user_id}")
def saldos(telegram_user_id: int):
    return {"test": telegram_user_id}

@router.get("/networth/{telegram_user_id}")
def networth(telegram_user_id: int):
    return {"ok": True}

@router.get("/neto/{telegram_user_id}")
def neto(telegram_user_id: int):
    return {"ok": True}
