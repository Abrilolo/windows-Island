# Viabilidad: qué se puede implementar y qué no

> Revisado el 2026-11-06 contra la doc de Fenn ([fenn-platform.md](fenn-platform.md)),
> la referencia de hooks de Claude Code (<https://code.claude.com/docs/en/hooks>)
> y la de Codex (<https://learn.chatgpt.com/docs/hooks>).

Leyenda:

- ✅ **Viable**: se puede hacer con lo que hay y está verificado.
- ⚠️ **Viable con condiciones**: depende de algo externo, permisos, o falta verificarlo.
- ❌ **No viable** (o no vale la pena) con Fenn tal como es hoy.
- 🟢 **Ya existe** en el repo.

Recordatorio: Fenn limita **la UI**, no la lógica. Casi todo lo que aparece como ❌ es por la interfaz o por el servicio externo, no por Python.

---

## Resumen

| Módulo | Estado | Fase | Bloqueo principal |
|---|---|---|---|
| A1 AI Agents | ✅ (Gemini ⚠️) | 1 | Ninguno para Claude/Codex |
| A2 Git Control | ✅ | 2 | Solo polling (sin webhooks) |
| A3 Dev Center | ✅ / ❌ terminal embebida | 2 | No se puede mostrar una terminal |
| A4 Automation Hub | ✅ con lista blanca | 3 | Seguridad, no técnico |
| B1 Daily Planner | ⚠️ | 3 | API del launcher Android + OAuth de calendario |
| B2 Workspace Hub | ✅ | 3 | Ninguno |
| C1 System Monitor | ✅ / ⚠️ temperaturas | 4 | GPU/temps requieren LibreHardwareMonitor |
| C2 Device Center | ✅ teléfono / ⚠️ Bluetooth y audio | 4 | APIs WinRT poco documentadas |
| C3 Media Center | ⚠️ | 4 | Revisar si Fenn ya trae un built-in |
| D1 Lector de reels | ⚠️ | 3–4 | Obtener el contenido del reel |
| D2 Insights | ✅ | 5 | Necesita datos acumulados (SQLite) |
| Perfiles Work/Personal/Focus | ⚠️ parcial | 5 | Un plugin no puede ocultar tiles de otros |
| Voz a texto | ✅ | 4 | Modelo local (CPU/GPU) |

---

## A1 · AI Agents (Fase 1)

| Función | Estado | Cómo |
|---|---|---|
| Sesiones recientes, duración, rendimiento de Claude/Codex/Gemini | 🟢 | `core/agents/` lee los logs de sesión locales. |
| Saber al instante que una sesión empezó, terminó o se detuvo | ✅ | Hooks `SessionStart`, `Stop`, `SessionEnd`, `Notification` (Claude Code y Codex los tienen). |
| **Aprobar o rechazar desde la isla** (Claude Code) | ✅ | Hook `PermissionRequest`. Corre *en paralelo* al diálogo de la terminal: **el primero que decide gana**, así que la terminal sigue sirviendo de respaldo. Claude Code acepta hooks tipo `http` (POST directo a un servidor local) y tipo `command`. Timeout por defecto de 600 s. |
| **Aprobar o rechazar desde la isla** (Codex) | ✅ | Hook `PermissionRequest` con `{"decision": {"behavior": "allow" \| "deny"}}`. Codex solo soporta hooks `command` (no `http`): un script Python pequeño que llama al servidor local y espera. Codex pide revisar y confiar (`/hooks`) cada hook nuevo o modificado. |
| Gemini CLI: eventos y aprobaciones | ⚠️ | **Por verificar** si su sistema de hooks permite decidir aprobaciones. Mientras tanto: solo lectura de logs (ya existe). |
| Ver el diff o el resultado | ⚠️ | No hay visor de diffs. Mostrar un resumen (`+45 −12`, archivos) con `text mono` y un botón que haga `open` del archivo o carpeta en VS Code. |
| Ver la terminal del agente en vivo | ❌ | Fenn no puede incrustar una terminal y leer la terminal de otro proceso es frágil. Se usan los hooks. |
| Escribir un prompt al agente desde la isla | ❌ (por ahora) | No hay una API estable para inyectar texto en una sesión interactiva abierta. Una sesión *nueva* no interactiva (`claude -p`, `codex exec`) sí es posible, pero eso es otra funcionalidad. |

### Diseño recomendado para las aprobaciones

No hace falta un backend FastAPI aparte para esto. El plugin `agent-monitor` corre en modo `live`, así que **Fenn ya mantiene vivo ese proceso** y lo reinicia si se cae. Ese mismo proceso puede escuchar en `127.0.0.1:<puerto>`:

```
Claude Code ──(hook http POST)──┐
Codex ──(hook command: script)──┤
                                ▼
            plugin agent-monitor (live) · HTTP en 127.0.0.1:8787
                 │  1. guarda la solicitud pendiente
                 │  2. badge pulse + show → abre el notch en la page
                 │  3. el usuario pulsa Aprobar / Rechazar
                 ▼
            responde al hook → el agente continúa
```

Si Fenn no está corriendo, la conexión falla, el hook termina sin decidir y aparece el diálogo normal de la terminal. **Nunca se queda bloqueado.**

Reglas:

- Puerto distinto de **8765** (ese es el del teléfono). Propuesta: `8787`.
- Escuchar solo en `127.0.0.1` y exigir un token compartido (archivo en `FENN_DATA_DIR`) para que otro programa local no pueda aprobar.
- Si el usuario no responde en N segundos, no decidir (devolver nada) para que gane la terminal.

---

## A2 · Git Control (Fase 2)

| Función | Estado | Cómo |
|---|---|---|
| PR/MR abiertos, revisiones pendientes, estado de pipelines | ✅ | `gh` / `glab` o las APIs REST. Modo `poll` con `interval` de 60–120 s, o `live` con un timer. |
| Rama actual de cada repo del Workspace | ✅ | `git` local. Sin red. |
| Notificaciones instantáneas por webhook | ❌ | Un webhook necesita una URL pública. Usamos polling. |
| Tokens | ✅ | `keyring` (Windows Credential Manager). Nunca en `config.json` ni en el repo. |

Hay que cuidar el rate limit: el polling debe ser moderado y con caché.

---

## A3 · Dev Center (Fase 2)

| Función | Estado | Cómo |
|---|---|---|
| Contenedores Docker (estado, start/stop) | ✅ | `docker` CLI o la API local. Stop/remove con confirmación. |
| Servidores locales y puertos en uso | ✅ | `psutil` (procesos + puertos en escucha). |
| Abrir un proyecto en VS Code | ✅ | Mensaje `open` con la carpeta, o `code <ruta>`. |
| Terminal embebida en la isla | ❌ | No existe componente de terminal. |

---

## A4 · Automation Hub (Fase 3)

| Función | Estado | Cómo |
|---|---|---|
| Ejecutar scripts predefinidos | ✅ | Lista blanca en un archivo de config. Cada script tiene nombre, comando y si necesita confirmación. |
| Encadenar acciones | ✅ | Secuencias definidas en la config. |
| Ejecutar un comando escrito a mano | ❌ | No se hará, por las reglas de seguridad. |

---

## B1 · Daily Planner (Fase 3)

| Función | Estado | Cómo |
|---|---|---|
| Enviar notas y tareas al teléfono | 🟢 | `sync.phone_connector` (UDP → HTTP → ADB). |
| Leer tareas o hábitos *desde* el launcher Android | ⚠️ | Depende de que el launcher exponga un endpoint de lectura. Hoy solo hay `/api/v1/health` e `/ingest`. |
| Calendario (Google / Outlook) | ⚠️ | API oficial con OAuth: **tú haces el consentimiento** la primera vez y el token se guarda en Credential Manager. |
| Pomodoro / temporizador | ✅ | `badge ring` con progreso y label en la pill. |
| Finanzas | ⚠️ | Solo con datos que ya tengas (CSV o tu launcher). No se conecta a bancos. |

---

## B2 · Workspace Hub (Fase 3)

| Función | Estado | Cómo |
|---|---|---|
| Proyectos recientes, abrir carpetas, repos o docs | ✅ | Recorrer `C:\Workspace` y abrir con `open`. Usa tu estructura actual, no crea otra. |
| Soltar archivos sobre la isla | ✅ | `accepts_files = true` → evento `files` con las rutas. |

---

## C1 · System Monitor (Fase 4)

| Función | Estado | Cómo |
|---|---|---|
| CPU, RAM, disco, red | ✅ | `psutil` + `sparkline` o `ring`. Actualizar cada 2–5 s y solo mientras la página está abierta (`page_open` / `page_close`). |
| Temperaturas, GPU, ventiladores | ⚠️ | Necesita LibreHardwareMonitor corriendo (su servidor web o WMI). Puede requerir admin. |

---

## C2 · Device Center (Fase 4)

| Función | Estado | Cómo |
|---|---|---|
| Estado y conexión del teléfono | 🟢 | `connect_to_phone()`. |
| Batería del teléfono | ⚠️ | Solo si el launcher la expone por la API. |
| Volumen y mute del PC | ✅ | `pycaw` (Core Audio). |
| Cambiar el dispositivo de salida de audio | ⚠️ | Windows no tiene una API pública oficial. Se usa `AudioDeviceCmdlets` (PowerShell) o la interfaz no documentada `IPolicyConfig`. |
| Dispositivos Bluetooth y su batería | ⚠️ | WinRT (`winrt-Windows.Devices.*`) o `bleak`. No todos los dispositivos reportan batería. |

---

## C3 · Media Center (Fase 4)

| Función | Estado | Cómo |
|---|---|---|
| Lo que está sonando + play/pausa/siguiente | ⚠️ | WinRT `GlobalSystemMediaTransportControlsSessionManager` (paquete `winrt-Windows.Media.Control`). **Revisar primero si Fenn ya trae un módulo built-in de música**, para no duplicarlo. |

---

## D1 · Lector de reels inteligente (Fase 3–4)

La clasificación es la parte fácil. **Lo difícil es conseguir el contenido.**

| Función | Estado | Cómo |
|---|---|---|
| Clasificar en EXERCISE / BOOK / TOOL / BUY / IDEA | ✅ | `core/brain/` con Ollama ya clasifica texto. Los enums ya están en `core/contracts/schemas.py` (`ReelAspect`). |
| Recibir lo que compartes desde el teléfono | ✅ | El launcher Android recibe el *share* (URL + texto del caption) y lo envía al PC (o el PC lo recoge). |
| Descargar el video y leer el caption automáticamente | ⚠️ | Instagram/TikTok bloquean el scraping y va contra sus términos. `yt-dlp` funciona a veces pero se rompe. **Alternativa robusta:** compartir el archivo del video o el texto, no solo el enlace. |
| Transcribir el audio del reel | ✅ | `faster-whisper` local, si tienes el archivo. |
| Entender el video (sin audio ni caption) | ⚠️ | Modelo de visión local (p. ej. `llava` en Ollama). Pesado y lento. Para una fase posterior. |
| Guardar como rutina, lista de lectura o wishlist | ✅ | SQLite + mostrarlo en la page con `list`. |

---

## D2 · Insights (Fase 5)

| Función | Estado | Cómo |
|---|---|---|
| Uso de agentes, tiempo por proyecto, tendencias | ✅ | Agregaciones en SQLite + `sparkline`, `ring` o `canvas` para gráficos propios. Necesita semanas de datos. |

---

## Funciones transversales

| Función | Estado | Notas |
|---|---|---|
| Perfiles Work / Personal / Focus | ⚠️ parcial | No hay concepto de perfil global en Fenn y un plugin **no puede ocultar ni reordenar** tiles de otros. Lo que sí se puede: un archivo de perfil compartido (p. ej. `%APPDATA%\Fenn\plugin-data\_shared\profile.json`) que cada plugin lee para mostrar menos cosas o silenciar badges. |
| Modo No molestar / Focus Assist de Windows | ❌ | No hay API pública estable para activarlo desde código. |
| Voz a texto para enviar al teléfono | ✅ | El proceso del plugin graba con `sounddevice` al pulsar el `hotkey` y transcribe con `faster-whisper`. La `ring` del badge muestra que está grabando. |
| Notificación de alerta | ✅ | `badge pulse` + `show` (abre el notch en tu página). |
| Comunicación entre plugins | ⚠️ | No la hay en el protocolo. Usar SQLite compartida o el HTTP local del plugin que tenga el dato. |
| Tokens y secretos | ✅ | `keyring` → Windows Credential Manager. |

---

## ¿Cuándo hace falta el backend FastAPI?

**Todavía no.** Para las Fases 1–3 alcanza con:

1. Una **librería compartida** (`core/`) que importan todos los plugins: protocolo, contratos, conexión al teléfono, Ollama, SQLite.
2. Plugins `live` que, cuando necesitan recibir eventos externos (hooks), abren su propio HTTP local.

El motor centralizado se justifica cuando **dos o más plugins necesiten el mismo estado en vivo** (por ejemplo, que Insights lea en tiempo real lo que publica AI Agents) o cuando haya trabajo pesado que no deba repetirse por plugin. Si se crea, conviene que lo arranque un plugin `live` (Fenn lo mantiene vivo) en lugar de un servicio de Windows aparte.

## Pendientes de verificar

- [ ] Hooks de Gemini CLI: ¿permiten decidir aprobaciones?
- [ ] ¿Respeta el Fenn instalado la variable `FENN_PLUGIN_PATH`, o solo cuando se compila desde el código? (Si la respeta, se puede cargar `plugins/` del repo sin copiar archivos.)
- [ ] Módulos built-in que ya trae Fenn (música, batería, etc.) para no duplicarlos.
- [ ] Qué endpoints expone el launcher Android además de `health` e `ingest`.
