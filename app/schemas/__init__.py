from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Base para schemas de respuesta.

    extra='forbid' hace que Pydantic lance ValidationError si el servicio
    devuelve un campo que no está declarado en el schema, en vez de
    descartarlo silenciosamente.
    """
    model_config = ConfigDict(extra="forbid")
