# BotFinanzas - API

Este repositorio contiene el backend de BotFinanzas, un servicio desarrollado en Python que utiliza FastAPI para exponer una interfaz REST y LangChain para la gestión de inteligencia artificial aplicada a finanzas personales. El sistema no solo actúa como un CRUD de transacciones, sino que implementa un agente capaz de interpretar lenguaje natural para interactuar con la base de datos.

## Arquitectura Técnica

La API está estructurada para separar la lógica de persistencia de la lógica de procesamiento de lenguaje:

*   **Motor de API:** FastAPI, aprovechando la asincronía y la validación de datos nativa mediante Pydantic.
*   **Capa de Inteligencia:** Integración de LangChain con modelos de OpenAI. Se utiliza un agente que emplea herramientas (tools) específicas para consultar o modificar la base de datos según la intención del usuario.
*   **Persistencia:** SQLAlchemy como ORM para la gestión de modelos relacionales, facilitando la portabilidad entre motores de base de datos (SQLite/PostgreSQL).
*   **Esquemas y Modelos:** Separación clara entre los modelos de la base de datos (`models.py`) y los esquemas de validación de datos (`schemas.py`).

## Componentes Principales

### Agente y Herramientas (Tools)
A diferencia de una API tradicional, este backend utiliza un agente de LangChain. Este componente analiza el prompt del usuario y decide qué función ejecutar (por ejemplo, registrar un gasto o consultar un balance) conectando directamente la lógica del LLM con las operaciones de la base de datos.

### Gestión de Datos (CRUD)
El archivo `crud.py` centraliza las operaciones de lectura y escritura, permitiendo que tanto los endpoints estándar como el agente de IA interactúen con la base de datos de forma consistente.

### Endpoints
*   **Procesamiento de Mensajes:** Punto de entrada para el chat, donde el LLM procesa la entrada y devuelve una respuesta estructurada.
*   **Gestión Financiera:** Endpoints para la administración directa de ingresos, egresos y categorías.

## Stack de Tecnologías

*   **Lenguaje:** Python 3.10+
*   **Framework Web:** FastAPI
*   **IA/LLM:** LangChain / OpenAI API
*   **ORM:** SQLAlchemy
*   **Validación:** Pydantic
*   **Entorno:** Gestión de variables mediante `python-dotenv` para claves de API y configuraciones de base de datos.

## Configuración y Estructura

El proyecto requiere una estructura de variables de entorno para funcionar correctamente, específicamente para la conexión con OpenAI y la configuración de la base de datos local.

Estructura de archivos clave:
*   `main.py`: Punto de entrada de la aplicación y definición de rutas.
*   `database.py`: Configuración de la sesión y conexión con el motor de base de datos.
*   `models.py`: Definición de las tablas (usuarios, transacciones, etc.).
*   `agent.py`: (O lógica equivalente) Donde se configura el comportamiento del bot y sus capacidades de decisión.

## Estado del Proyecto

El backend está funcional como motor de procesamiento para el frontend de BotFinanzas, permitiendo una interacción fluida donde el usuario no necesita llenar formularios complejos, sino simplemente describir sus movimientos financieros.

---

**Autor:** [G-Gamboa](https://github.com/G-Gamboa)  
**Repositorio:** [BotFinanzasAPI](https://github.com/G-Gamboa/BotFinanzasAPI)