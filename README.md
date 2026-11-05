# nook-bridge

Puente local (Windows -> Android `Minimal Launcher`) para la barra flotante **Nook / Fenn** (`nooknotch.xyz`) con inferencia local bajo demanda vía **Ollama**.

## Conexión reutilizable al Galaxy S24+ (`src/sync/phone_connector.py`)

Cualquier plugin de Nook/Fenn puede conectarse y enviar datos al Galaxy S24+ (`Minimal Launcher` en el puerto `8765`) importando las funciones de `sync` (o `sync.phone_connector`), sin depender de `OutboxStore` ni del estado interno de `minimal-bridge`.

### Estrategia de conexión en 3 niveles (`connect_to_phone`)

1. **`transport="udp"` (LAN Wi-Fi Discovery):** Envía `NOOK_DISCOVER` por broadcast UDP (`255.255.255.255:8765`), subredes locales y vecinos ARP activos; al recibir respuesta del teléfono, hace `GET /api/v1/health` con la cabecera `X-Nook-Client-Ip` para encender el indicador `● PC`.
2. **`transport="http"` (Fallback HTTP LAN):** Si el router descarta paquetes broadcast UDP, prueba directamente `GET /api/v1/health` contra la última IP guardada en `config.json` e IPs conocidas de la LAN.
3. **`transport="adb"` (Fallback por túnel ADB USB / Wireless):** Si la red Wi-Fi de invitados tiene *AP Client Isolation* (bloqueando tráfico entre clientes Wi-Fi), ejecuta automáticamente `adb forward tcp:8765 tcp:8765` y conecta a través de `http://127.0.0.1:8765`.

### Ejemplo de uso desde cualquier otro plugin

```python
from sync import connect_to_phone, post_to_phone, send_message_to_phone

# 1. Conectar y consultar el estado / transporte usado ("udp", "http", "adb" o "offline")
conn = connect_to_phone()
if conn.connected:
    print(f"Conectado a S24+ en {conn.ip}:{conn.port} vía {conn.transport}")

# 2. Enviar un mensaje directo desde otro plugin (con reconexión automática)
ok, err = send_message_to_phone("Sesión de agente finalizada", source="Claude")

# 3. Enviar un payload estructurado a /api/v1/ingest
ok, err = post_to_phone({"notes": [{"category": "WORK", "text": "Revisar PR"}]})
```

### Despliegue en Nook / Fenn

```powershell
.\scripts\deploy.ps1
```
