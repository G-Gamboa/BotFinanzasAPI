from fastapi import APIRouter

router = APIRouter()

@router.get("/finance-test")
def finance_test():
    return {"ok": True}
