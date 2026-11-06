# Fenn: qué permite la plataforma y qué no

> Fuente: documentación oficial <https://fenn.click/docs> (antes `nooknotch.xyz`), revisada el 2026-11-06.
> Protocolo `1`. Si Fenn cambia de versión, vuelve a revisar `messages`, `views` y `canvas`.

## La regla que lo resume todo

**Fenn limita la interfaz, no la lógica.**

Un plugin es un programa normal (Python en nuestro caso) que Fenn arranca como proceso propio. Ese programa puede hacer todo lo que Python puede hacer en Windows: red, archivos, SQLite, micrófono, llamar a `gh`, `docker`, PowerShell, abrir un servidor HTTP local, etc.

Lo único que Fenn controla es **cómo se dibuja**: el plugin imprime JSON describiendo la vista y Fenn la pinta con su propio estilo (egui / Rust). No hay navegador.

| Pregunta | Respuesta |
|---|---|
| ¿Puedo usar HTML, CSS, JS, SVG o un webview? | **No.** Solo componentes JSON de Fenn. |
| ¿Puedo dibujar formas libres? | **Sí**, con el componente `canvas` (rect, circle, line, polygon, arc, text, icon). |
| ¿Puedo mostrar una imagen? | **Sí**, `image` con PNG/JPG/BMP (ruta o base64). Sin interactividad salvo el clic del tile. |
| ¿Puedo elegir colores? | **Sí**: nombres del tema (`text dim faint accent on_accent`), colores fijos o `#RRGGBBAA`. |
| ¿Puedo controlar el blur, el cristal o las animaciones de apertura? | **No.** Los pone Fenn. |
| ¿Puedo lanzar notificaciones de Windows (toast)? | No desde el protocolo. Usa `badge` + `show`. (Un toast nativo se podría hacer desde Python aparte.) |
| ¿Puede un plugin hablar con otro plugin? | **No hay mecanismo en el protocolo.** Si hace falta, hay que usar algo propio (archivo, SQLite o HTTP local). |
| ¿Puede un plugin ocultar o mover tiles de otros? | **No.** Cada plugin solo dibuja lo suyo. |
| ¿Puedo leer el portapapeles? | No desde el protocolo (solo escribir con `copy`). Desde Python sí se puede. |

## Cómo corre un plugin

- Carpeta con `plugin.toml` + programa. Fenn busca en: `%APPDATA%\Fenn\plugins`, `plugins\` junto a `fenn.exe` y cada carpeta de `FENN_PLUGIN_PATH` (separadas por `;`). Si dos plugins tienen el mismo `id`, gana el primero encontrado.
- **Un `plugin.toml` = un plugin = un tile.** Un repo con varios plugins necesita una carpeta con su propio `plugin.toml` por cada uno.
- Modos:
  - `live` (default): un proceso persistente. Para sockets, timers, estado y animación. Si muere, Fenn lo reinicia a los 2 s, hasta 3 veces por minuto.
  - `poll`: Fenn ejecuta el programa cada `interval` segundos (o al hacer clic) y lee lo que imprime. Máximo 30 s por ejecución. El evento que lo causó llega en `FENN_EVENT`.
- Variables de entorno útiles: `FENN_DATA_DIR` (`%APPDATA%\Fenn\plugin-data\<id>`, **guarda aquí datos y config**, no en la carpeta del plugin), `FENN_THEME`, `FENN_ACCENT`, `FENN_PLUGIN_DIR`.
- Dev mode (Settings de Fenn): recarga el plugin cada vez que guardas un archivo de su carpeta.
- Log: `%APPDATA%\Fenn\fenn.log` (stderr del plugin + líneas JSON rechazadas con el motivo).

## Espacio real para dibujar

Esto es **muy pequeño** y condiciona todo el diseño:

| Destino | Ancho × alto (puntos) |
|---|---|
| tile `small` (1x1) | 44 × 44 |
| tile `wide` (2x1) | 104 × 36 |
| tile `large` (2x2) | 104 × 104 |
| page (default) | 536 × 168 (ajustable con `page_size = [w, h]`) |

El usuario puede redimensionar el tile; Fenn avisa del tamaño real con el mensaje `layout`.

Consecuencia: **un tile `wide` cabe en una o dos líneas** (icono + texto + quizás un botón). Los detalles, listas y botones de Aprobar/Rechazar van en la **page**.

## Mensajes

### Plugin → Fenn (stdout, una línea JSON por mensaje, con flush)

| `type` | Para qué |
|---|---|
| `tile` | Reemplaza el tile. |
| `page` | Reemplaza la página (se abre al hacer clic en el tile). `actions`: botones redondos en la cabecera. |
| `badge` | Algo en la pill contraída: `ring` (progreso + label), `glyph` (icono) o `pulse` (punto pulsante). `null` lo limpia. |
| `active` | Ilumina el tile con el color de acento. |
| `open_page` / `close_page` | Abre o cierra tu página si el panel está abierto. |
| `show` | **Abre el notch, fijado, en tu página.** Es la forma de hacer una alerta. |
| `copy` | Copia texto al portapapeles. |
| `open` | Abre una URL, archivo o carpeta con su app por defecto. |
| `log` | Escribe en el log de Fenn. |

### Fenn → plugin (stdin, solo modo `live`)

`hello`, `event` (`click change submit commit`), `tile_click`, `page_open` / `page_close`, `layout`, `theme`, `hotkey`, `files` (requiere `accepts_files = true`), `shutdown` (tienes 0.4 s para guardar).

## Componentes

- **Layout:** `column`, `row`, `grid`, `card`, `spacer`, `divider`.
- **Contenido:** `text` (`size`: small, body, title, big, huge; `mono`, `bold`, `wrap`), `icon` (Phosphor, 1.530 iconos), `image`, `progress`, `ring`, `sparkline`, `list` (filas clicables), `canvas`.
- **Controles:** `button`, `toggle`, `slider`, `input` (con `live` para cada tecla), `chips`.
- Un tipo desconocido se dibuja como nada (no rompe).
- Mantén los `id` estables entre redibujados.

Detalle de campos: <https://fenn.click/docs/views> y <https://fenn.click/docs/canvas>.

## Herramientas oficiales que conviene usar

- **SDK Python** `sdk/python/fenn.py` (un archivo, sin dependencias): builders, `load`/`save` en `FENN_DATA_DIR`, `@app.on(id)`, `@app.every(seg)`. Hoy tenemos nuestro propio `core/protocol/`; decidir si migrar al SDK o mantener el nuestro.
- **Skill `fenn-plugin` para Claude Code** + checker:
  `python "$HOME\.claude\skills\fenn-plugin\scripts\check_plugin.py" <carpeta> --event id:click`
  Ejecuta el plugin como Fenn y valida cada línea. Úsalo en CI o antes de desplegar.
- Probar sin Fenn: `'{"type":"event","id":"x","kind":"click"}' | python main.py`.

## Si algún día los componentes no bastan

- Renderizar algo a PNG y mostrarlo con `image` (caro, sin interacción).
- Escribir un **módulo built-in en Rust** dentro de Fenn y mandar un PR (para dibujar cada frame con egui o llamar Win32 dentro del proceso). Solo si de verdad hace falta.
