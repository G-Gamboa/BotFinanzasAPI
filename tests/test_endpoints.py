"""
Capa 3: Tests de integración — TestClient + SQLite en memoria.

Cubre los flujos críticos: crear movimiento, anular, historial, categorías,
preferencias y el endpoint de notificaciones del cron.
"""
import pytest


USER_ID = 999_999_999


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mov_payload(**overrides):
    base = {
        "telegram_user_id": USER_ID,
        "movement_type": "EGR",
        "movement_date": "2026-06-01",
        "amount": 150.0,
        "note": "Test",
        "category_name": "Alimentación",
        "payment_method": "cash",
        "account_name": "Efectivo",
    }
    return {**base, **overrides}


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Movimientos ───────────────────────────────────────────────────────────────

class TestMovimientos:
    def test_crear_ingreso_ok(self, client, user_accounts, user_categories):
        r = client.post("/movimientos", json=_mov_payload(
            movement_type="ING",
            category_name="Salario",
        ))
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_crear_egreso_ok(self, client, user_accounts, user_categories):
        # Fondear la cuenta antes de gastar
        client.post("/movimientos", json=_mov_payload(
            movement_type="ING", category_name="Salario",
        ))
        r = client.post("/movimientos", json=_mov_payload())
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "id" in body

    def test_monto_cero_rechazado(self, client, user_accounts, user_categories):
        r = client.post("/movimientos", json=_mov_payload(amount=0))
        assert r.status_code == 422

    def test_fecha_invalida_rechazada(self, client, user_accounts, user_categories):
        r = client.post("/movimientos", json=_mov_payload(movement_date="no-es-fecha"))
        assert r.status_code in (400, 422)

    def test_anular_movimiento(self, client, user_accounts, user_categories):
        # Fondear la cuenta antes del egreso
        client.post("/movimientos", json=_mov_payload(
            movement_type="ING", category_name="Salario",
        ))
        # Crear egreso para luego anular
        create_r = client.post("/movimientos", json=_mov_payload())
        assert create_r.status_code == 200
        mov_id = create_r.json()["id"]

        # Anular
        anular_r = client.patch(
            f"/movimientos/{mov_id}/anular",
            json={"reason": "Error de prueba"},
        )
        assert anular_r.status_code == 200
        assert "anulado" in anular_r.json()["message"].lower()

    def test_anular_movimiento_inexistente(self, client):
        r = client.patch("/movimientos/999999/anular", json={"reason": "x"})
        assert r.status_code == 400


# ── Historial ─────────────────────────────────────────────────────────────────

class TestHistorial:
    def test_historial_vacio(self, client):
        r = client.get(f"/historial/{USER_ID}")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert isinstance(body["items"], list)

    def test_historial_con_movimiento(self, client, user_accounts, user_categories):
        # ING no requiere saldo previo — suficiente para verificar que historial no está vacío
        client.post("/movimientos", json=_mov_payload(
            movement_type="ING", category_name="Salario",
        ))
        r = client.get(f"/historial/{USER_ID}")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

    def test_historial_filtro_tipo(self, client, user_accounts, user_categories):
        client.post("/movimientos", json=_mov_payload(
            movement_type="ING", category_name="Salario",
        ))
        client.post("/movimientos", json=_mov_payload())  # EGR (ya hay saldo)
        r = client.get(f"/historial/{USER_ID}?movement_type=EGR")
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            assert item["movement_type"] == "EGR"

    def test_historial_filtro_categoria(self, client, user_accounts, user_categories):
        client.post("/movimientos", json=_mov_payload(
            movement_type="ING", category_name="Salario",
        ))
        client.post("/movimientos", json=_mov_payload())  # EGR Alimentación
        r = client.get(f"/historial/{USER_ID}?movement_type=EGR&category_name=Alimentaci%C3%B3n")
        assert r.status_code == 200


# ── Categorías ────────────────────────────────────────────────────────────────

class TestCategorias:
    def test_listar_categorias(self, client, user_categories):
        r = client.get(f"/categorias/{USER_ID}")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert len(body["items"]) >= 2

    def test_crear_categoria_ok(self, client):
        r = client.post("/categorias", json={
            "telegram_user_id": USER_ID,
            "name": "Nueva Cat",
            "kind": "EGR",
            "sort_order": 99,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_crear_categoria_nombre_vacio_rechazado(self, client):
        r = client.post("/categorias", json={
            "telegram_user_id": USER_ID,
            "name": "",
            "kind": "EGR",
            "sort_order": 1,
        })
        assert r.status_code in (400, 422)


# ── Preferencias ──────────────────────────────────────────────────────────────

class TestPreferencias:
    def test_get_preferencias(self, client, test_user):
        r = client.get(f"/preferencias/{USER_ID}")
        assert r.status_code == 200
        body = r.json()
        assert "usd_to_gtq" in body
        assert "default_tab" in body

    def test_patch_preferencias(self, client, test_user):
        r = client.patch("/preferencias", json={
            "telegram_user_id": USER_ID,
            "show_amounts_default": True,
            "default_tab": "dashboard",
            "usd_to_gtq": 7.85,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── Cron: notify-daily ────────────────────────────────────────────────────────

class TestNotifyDaily:
    def test_sin_secret_rechazado(self, client):
        r = client.post("/admin/notify-daily")
        assert r.status_code == 401

    def test_secret_incorrecto_rechazado(self, client):
        r = client.post(
            "/admin/notify-daily",
            headers={"Authorization": "Bearer secreto-incorrecto"},
        )
        assert r.status_code == 401

    def test_secret_correcto_ok(self, client, test_user):
        r = client.post(
            "/admin/notify-daily",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "sent" in body
        assert "errors" in body
        assert "date" in body

    def test_respuesta_tiene_estructura_correcta(self, client, test_user):
        r = client.post(
            "/admin/notify-daily",
            headers={"Authorization": "Bearer test-secret"},
        )
        body = r.json()
        assert isinstance(body["sent"], int)
        assert isinstance(body["errors"], int)
        assert isinstance(body["skipped"], int)
