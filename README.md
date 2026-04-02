# BotFinanzas - API

Este repositorio contiene el backend de BotFinanzas, una API RESTful construida con Python y FastAPI diseñada para la gestión integral de finanzas personales. El sistema se encarga de la persistencia de datos, la lógica de presupuestos y la seguridad de la información del usuario.

## Propósito del Proyecto

La API funciona como el núcleo de procesamiento de datos para la plataforma BotFinanzas. Su arquitectura está orientada a gestionar transacciones financieras, categorización de gastos y el seguimiento de presupuestos mensuales, asegurando que el frontend tenga una interfaz de datos consistente y segura.

## Características Técnicas

### Gestión de Entidades Financieras
El sistema permite el control total sobre las operaciones básicas de finanzas personales:
*   **Transacciones:** Registro y seguimiento de ingresos y egresos.
*   **Categorías:** Organización personalizada de movimientos financieros.
*   **Presupuestos (Budgets):** Definición de límites de gasto por categoría y periodo.

### Seguridad y Autenticación
Implementación de un sistema de seguridad basado en estándares de la industria:
*   Autenticación de usuarios mediante **OAuth2** con tokens **JWT**.
*   Protección de credenciales utilizando hashing con `bcrypt`.
*   Middleware para la gestión de CORS, permitiendo la integración segura con el frontend.

### Estructura de Datos y Validación
*   **SQLAlchemy:** Uso de este ORM para la definición de modelos relacionales y la gestión de la base de datos.
*   **Pydantic:** Validación rigurosa de datos de entrada y salida mediante esquemas, garantizando que la API sea robusta ante datos mal formados.

## Stack Tecnológico

*   **Lenguaje:** Python 3.x
*   **Framework:** FastAPI
*   **Base de Datos / ORM:** SQLAlchemy
*   **Validación de Datos:** Pydantic
*   **Seguridad:** Passlib (bcrypt) y PyJWT

## Organización del Código

El proyecto sigue una estructura limpia y modular para facilitar su mantenimiento:

*   `models.py`: Definición de las tablas de la base de datos (SQLAlchemy).
*   `schemas.py`: Modelos de datos para las peticiones y respuestas (Pydantic).
*   `crud.py`: Lógica de acceso a datos y operaciones de base de datos.
*   `auth.py`: Lógica de generación y validación de tokens de acceso.
*   `main.py`: Punto de entrada de la aplicación y configuración de rutas.

## Próximos Objetivos Técnicos

*   Implementación de reportes agregados para análisis mensual automático.
*   Integración de lógica de procesamiento de lenguaje natural para la funcionalidad de "Bot".

---

**Autor:** [G-Gamboa](https://github.com/G-Gamboa)  
**Repositorio:** [BotFinanzasAPI](https://github.com/G-Gamboa/BotFinanzasAPI)
