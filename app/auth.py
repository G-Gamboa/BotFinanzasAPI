from fastapi import Header, HTTPException, status


def get_user_id_from_header(x_user_id: int | None = Header(default=None)) -> int | None:
    if x_user_id is None:
        return None
    if x_user_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='x-user-id inválido')
    return x_user_id
