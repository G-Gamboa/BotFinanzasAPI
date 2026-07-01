from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, VaultConfig, VaultItem


def _get_user(db: Session, telegram_user_id: int) -> User:
    user = db.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if not user:
        raise ValueError("Usuario no encontrado.")
    return user


def get_vault_config(db: Session, telegram_user_id: int) -> VaultConfig | None:
    user = _get_user(db, telegram_user_id)
    return db.scalar(select(VaultConfig).where(VaultConfig.user_id == user.id))


def setup_vault(db: Session, telegram_user_id: int, salt: str, dek_wrapped: str) -> VaultConfig:
    user = _get_user(db, telegram_user_id)
    existing = db.scalar(select(VaultConfig).where(VaultConfig.user_id == user.id))
    if existing:
        raise ValueError("La bóveda ya está configurada.")
    config = VaultConfig(user_id=user.id, salt=salt, dek_wrapped=dek_wrapped)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_vault_config(db: Session, telegram_user_id: int, salt: str, dek_wrapped: str) -> VaultConfig:
    """Cambia la contraseña maestra: reemplaza salt y dek_wrapped. El DEK (y todos los items) no cambian."""
    user = _get_user(db, telegram_user_id)
    config = db.scalar(select(VaultConfig).where(VaultConfig.user_id == user.id))
    if not config:
        raise ValueError("Bóveda no configurada.")
    config.salt = salt
    config.dek_wrapped = dek_wrapped
    db.commit()
    db.refresh(config)
    return config


def list_vault_items(db: Session, telegram_user_id: int) -> list[VaultItem]:
    user = _get_user(db, telegram_user_id)
    return db.scalars(
        select(VaultItem)
        .where(VaultItem.user_id == user.id)
        .order_by(VaultItem.updated_at.desc())
    ).all()


def create_vault_item(db: Session, telegram_user_id: int, ciphertext: str) -> VaultItem:
    user = _get_user(db, telegram_user_id)
    item = VaultItem(user_id=user.id, ciphertext=ciphertext)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_vault_item(db: Session, item_id: int, telegram_user_id: int, ciphertext: str) -> VaultItem:
    user = _get_user(db, telegram_user_id)
    item = db.get(VaultItem, item_id)
    if not item or item.user_id != user.id:
        raise ValueError("Item no encontrado.")
    item.ciphertext = ciphertext
    db.commit()
    db.refresh(item)
    return item


def delete_vault_item(db: Session, item_id: int, telegram_user_id: int) -> None:
    user = _get_user(db, telegram_user_id)
    item = db.get(VaultItem, item_id)
    if not item or item.user_id != user.id:
        raise ValueError("Item no encontrado.")
    db.delete(item)
    db.commit()
