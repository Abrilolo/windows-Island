# nook-bridge

Plugins locales para la barra flotante **Fenn** (antes Nook, <https://fenn.click>): puente Windows → Android `Minimal Launcher`, monitores de agentes de IA e inferencia local bajo demanda vía **Ollama**.

Antes de implementar algo nuevo, lee:

- [docs/fenn-platform.md](docs/fenn-platform.md): qué permite Fenn y qué no.
- [docs/feasibility.md](docs/feasibility.md): qué se puede implementar de cada módulo.
- [docs/design-system.md](docs/design-system.md): pill / tile / page con componentes de Fenn.
- [IDEA.md](IDEA.md): visión, módulos y roadmap.

## Estructura

```
core/                     # librería compartida que importan todos los plugins
├── protocol/             # builders del protocolo JSON-Lines de Fenn + theme.py
├── contracts/            # payload.py (Room v6, Android) + schemas.py (DTOs de plugins/engine)
├── phone/                # conexión y envío al Galaxy S24+ (UDP → HTTP → ADB)
├── brain/                # cliente Ollama
├── agents/               # parsers de sesiones Claude / Codex / Gemini + plugin monitor
└── mail/                 # (pendiente) escáner IMAP
plugins/                  # una carpeta = un plugin de Fenn (plugin.toml + main.py)
├── minimal-bridge/       # "Device Center": teléfono + notas rápidas → Ollama → Minimal Launcher
└── ai-agents/            # Claude Code + Codex + Gemini: actividad, sesiones y aprobaciones
scripts/                  # deploy, setup, utilidades
tests/
docs/
```

Cada `plugins/<id>/main.py` busca `core/` junto a sí mismo (copia instalada) o dos niveles arriba (repo), así que funciona igual desplegado o desde el checkout.

### Agregar un plugin nuevo

1. Crea `plugins/<id>/plugin.toml` (el `id` debe coincidir con el nombre de la carpeta) y `plugins/<id>/main.py` copiando el bloque de arranque de cualquier otro plugin.
2. Pon la lógica reutilizable en `core/` y la específica del plugin en `plugins/<id>/<paquete>/`.
3. `tests/test_plugin_layout.py` valida el manifiesto y que los ids y hotkeys no se repitan.
4. Despliega con `.\scripts\deploy.ps1 -Plugin <id>`.

## Conexión reutilizable al Galaxy S24+ (`core/phone/`)

Cualquier plugin puede conectarse y enviar datos al Galaxy S24+ (`Minimal Launcher` en el puerto `8765`) importando `core.phone`, sin depender de `OutboxStore` ni del estado interno de `minimal-bridge`.

### Estrategia de conexión en 3 niveles (`connect_to_phone`)

1. **`transport="udp"` (LAN Wi-Fi Discovery):** Envía `NOOK_DISCOVER` por broadcast UDP (`255.255.255.255:8765`), subredes locales y vecinos ARP activos; al recibir respuesta del teléfono, hace `GET /api/v1/health` con la cabecera `X-Nook-Client-Ip` para encender el indicador `● PC`.
2. **`transport="http"` (Fallback HTTP LAN):** Si el router descarta paquetes broadcast UDP, prueba directamente `GET /api/v1/health` contra la última IP guardada en `config.json` e IPs conocidas de la LAN.
3. **`transport="adb"` (Fallback por túnel ADB USB / Wireless):** Si la red Wi-Fi de invitados tiene *AP Client Isolation* (bloqueando tráfico entre clientes Wi-Fi), ejecuta automáticamente `adb forward tcp:8765 tcp:8765` y conecta a través de `http://127.0.0.1:8765`.

### Ejemplo de uso desde cualquier otro plugin

```python
from core.phone import connect_to_phone, post_to_phone, send_message_to_phone

# 1. Conectar y consultar el estado / transporte usado ("udp", "http", "adb" o "offline")
conn = connect_to_phone()
if conn.connected:
    print(f"Conectado a S24+ en {conn.ip}:{conn.port} vía {conn.transport}")

# 2. Enviar un mensaje directo desde otro plugin (con reconexión automática)
ok, err = send_message_to_phone("Sesión de agente finalizada", source="Claude")

# 3. Enviar un payload estructurado a /api/v1/ingest
ok, err = post_to_phone({"notes": [{"category": "WORK", "text": "Revisar PR"}]})
```

## Despliegue en Fenn

```powershell
.\scripts\deploy.ps1                                  # solo minimal-bridge
.\scripts\deploy.ps1 -Plugin ai-agents,minimal-bridge # plugins concretos
.\scripts\deploy.ps1 -All                             # todos los de plugins/
```

Cierra Fenn antes de desplegar un plugin que esté corriendo: Windows bloquea su carpeta. Luego vuelve a abrirlo.

Copia `plugins/<id>/` + `core/` a `%APPDATA%\Fenn\plugins\<id>` y apunta `run` al Python del `.venv`.

Destino único: `%APPDATA%\Fenn\plugins`. Los datos (`%APPDATA%\Fenn\plugin-data\<id>`) no se tocan al desplegar, así que la configuración del teléfono se conserva.

## Estado del entorno (2026-11-06)

- Instalados en Fenn desde este repo: `minimal-bridge` (se muestra como "Device Center") y `ai-agents` (un solo tile para Claude Code, Codex y Gemini), con el `.venv` del repo.
- Conexión al teléfono (`plugin-data\minimal-bridge\config.json`): `http://127.0.0.1:8765/api/v1/ingest`, que es el **túnel ADB** (`adb forward tcp:8765 tcp:8765`). Con el teléfono por USB/ADB y el launcher abierto, se conecta solo. La IP LAN anterior (`192.168.3.164`) está en el respaldo `%APPDATA%\Nook.legacy-20261106`.
- `%APPDATA%\Nook` (copia vieja) quedó renombrada a `Nook.legacy-20261106`. Fenn ya no la usa y se puede borrar.

## Fase 1: aprobaciones desde la isla

Cuando Claude Code o Codex piden permiso para una herramienta, la isla se abre con el comando y tres botones: **Aprobar**, **Rechazar** y **Terminal** (no decide y deja que aparezca el diálogo normal). Si no respondes en 120 s, pasa lo mismo que con *Terminal*.

- `ai-agents` escucha en `127.0.0.1:8787` para los dos agentes (el script indica cuál es en `fenn_agent`), con un token por arranque guardado en `plugin-datai-agents\hooks.json`.
- `hooks/fenn_hook.py` es el comando que ejecutan los agentes. Si Fenn no corre, sale al instante sin decidir.
- Diseño y límites: [docs/feasibility.md](docs/feasibility.md#diseño-implementado-fase-1).

Registrar los hooks (modifica `~/.claude/settings.json` y `~/.codex/hooks.json`, conserva los demás hooks y guarda un respaldo):

```powershell
.venv\Scripts\python.exe scripts\install_hooks.py            # ver qué cambiaría
.venv\Scripts\python.exe scripts\install_hooks.py --apply    # instalar
.venv\Scripts\python.exe scripts\install_hooks.py --uninstall --apply
```

En Codex, después de instalar, abre `codex` y usa `/hooks` para revisar y confiar en los hooks nuevos.

Probar sin un agente (abre la isla con una solicitud falsa):

```powershell
'{"hook_event_name":"PermissionRequest","tool_name":"Bash","tool_input":{"command":"echo hola"}}' | .venv\Scripts\python.exe hooks\fenn_hook.py claude
```

## Tests

```powershell
uv run pytest
```
