# Design system (componentes de Fenn)

Este documento reemplaza la versión HTML/CSS ([archive/visual-instructions-html.md](archive/visual-instructions-html.md)).
Fenn no renderiza HTML: cada vista es un árbol JSON de componentes que Fenn dibuja con su propio estilo de cristal.
Referencia de la plataforma: [fenn-platform.md](fenn-platform.md).

## Principios

1. **Los tres niveles se mantienen**: pill → tile → page.
2. **Fenn pone el cristal.** No se configuran el fondo, el blur, los bordes, las sombras ni las animaciones de apertura.
3. **Colores del tema primero** (`text`, `dim`, `faint`, `accent`, `on_accent`), para verse bien en modo claro y oscuro y con el acento del usuario. Los colores fijos solo para estados.
4. **El tile es diminuto** (`wide` = 104×36 pt). Un dato, un estado y como mucho un botón. Todo lo demás va en la page.
5. **Sin CPU en reposo.** Si nada cambia, no se envía nada.

## Tokens

El CSS original se traduce así:

| Token CSS original | En Fenn |
|---|---|
| `--bg-island`, `--bg-card`, `--backdrop-blur`, bordes | Lo dibuja Fenn (`card` agrupa contenido en un panel de cristal). |
| `--text-primary` | `"text"` |
| `--text-secondary` | `"dim"` |
| `--text-muted` | `"faint"` |
| `--accent-color` | `"accent"` (texto encima: `"on_accent"`) |
| `--status-active` (#22c55e) | `"green"` |
| `--status-waiting` (#f59e0b) | `"orange"` |
| `--status-error` (#ef4444) | `"red"` |
| `--font-mono` | `text` con `"mono": true` |
| Tamaños de fuente | `size`: `small`, `body`, `title`, `big`, `huge` |
| `--radius-*` | Lo decide Fenn. `canvas rect` e `image` aceptan `radius`/`rounding` propios. |

Ya existe en `core/protocol/theme.py`:

```python
TEXT, DIM, FAINT, ACCENT, ON_ACCENT = "text", "dim", "faint", "accent", "on_accent"

STATUS_COLOR = {
    "running": "green",
    "waiting": "orange",   # esperando aprobación o input
    "error": "red",
    "idle": "faint",
}

STATUS_ICON = {
    "running": "circle-notch",
    "waiting": "hand-palm",
    "error": "warning-circle",
    "idle": "moon",
}
```

Iconos: siempre de Phosphor (<https://phosphoricons.com>). `"fill": true` para la variante rellena.

## Nivel 1 · Pill (`badge`)

La pill es de Fenn; el plugin solo puede ponerle **una** de estas cosas:

| Badge | Cuándo usarlo |
|---|---|
| `{"kind": "pulse"}` | Algo requiere atención (aprobación pendiente, error). |
| `{"kind": "glyph", "icon": "robot"}` | Estado discreto y continuo (hay un agente trabajando). |
| `{"kind": "ring", "progress": 0.4, "label": "12:00"}` | Progreso o tiempo (pomodoro, grabación de voz). Reemplaza el reloj de la pill. |
| `null` | Limpiar cuando ya no hay nada que mostrar. |

No es posible mostrar texto libre tipo "Claude · Refactoring..." en la pill. Ese texto va en el tile.

Para una alerta que el usuario no se puede perder: `badge pulse` + mensaje `show` (abre el notch fijado en tu página).

## Nivel 2 · Tile

Espacio real: `small` 44×44, `wide` 104×36, `large` 104×104 puntos. Escucha el mensaje `layout` para adaptarte si el usuario lo redimensiona.

**Patrón base del tile `wide`:** icono de estado + una línea principal + una secundaria.

```json
{ "type": "row", "align": "center", "gap": 6, "children": [
  { "type": "icon", "icon": "hand-palm", "color": "orange", "size": 18 },
  { "type": "column", "gap": 0, "children": [
    { "type": "text", "text": "Claude", "size": "small", "bold": true },
    { "type": "text", "text": "Aprobación", "size": "small", "color": "orange" } ] } ] }
```

Reglas:

- Máximo **dos líneas** de texto `small` en `wide`. El texto largo se corta con "…" (está bien).
- Botones en el tile solo si son de **un icono** (`button` sin `label`) y la acción no es destructiva.
- **Aprobar / Rechazar nunca van en el tile**: van en la page, que tiene espacio para mostrar qué se está aprobando.
- Para un `large`: `ring` o `sparkline` como dato principal y texto debajo.

## Nivel 3 · Page

Por defecto 536×168 pt. Si un módulo necesita más alto, define `page_size = [536, 320]` en su `plugin.toml`. Usa `"scroll": true` en la columna raíz cuando el contenido pueda crecer.

**Estructura base:**

```
column (scroll)
├── row: título · spacer · chips de contexto
├── list | card(s): contenido principal
└── row: spacer · acciones (botón secundario, botón primary)
```

Los botones de cabecera (refrescar, configuración) van en `actions` del mensaje `page`, no dentro de la vista.

### Ejemplo: solicitud de aprobación

```json
{ "type": "page",
  "actions": [{ "id": "refresh", "icon": "arrows-clockwise", "tooltip": "Actualizar" }],
  "view": { "type": "column", "gap": 8, "scroll": true, "children": [
    { "type": "row", "align": "center", "children": [
      { "type": "icon", "icon": "terminal-window", "color": "accent" },
      { "type": "text", "text": "Claude Code · nook-bridge", "size": "title" },
      { "type": "spacer" },
      { "type": "text", "text": "Work", "size": "small", "color": "dim" } ] },
    { "type": "card", "children": [
      { "type": "text", "text": "Bash", "size": "small", "color": "dim" },
      { "type": "text", "text": "pytest tests/test_auth.py --verbose", "mono": true, "wrap": true } ] },
    { "type": "row", "children": [
      { "type": "spacer" },
      { "type": "button", "id": "deny",    "label": "Rechazar", "icon": "x" },
      { "type": "button", "id": "approve", "label": "Aprobar",  "icon": "check", "primary": true } ] } ] } }
```

### Ejemplo: timeline de eventos

La timeline del diseño original se hace con `list`:

```json
{ "type": "list", "items": [
  { "id": "ev1", "icon": "check-circle",   "title": "Read workspace config",     "subtitle": "11:02:14 · 12 ms" },
  { "id": "ev2", "icon": "pencil-simple",  "title": "src/api/routes.py",         "subtitle": "11:02:40", "trailing": "+45 −12" },
  { "id": "ev3", "icon": "hand-palm",      "title": "Esperando aprobación",      "subtitle": "11:03:02", "selected": true } ] }
```

`list` no deja colorear cada fila. El estado se comunica con el **icono**.

## Gráficos propios (`canvas`)

Para gauges, mini-gráficos o indicadores que los componentes no cubren. Coordenadas en puntos desde la esquina superior izquierda. Ángulos en grados, en sentido horario desde las 12.

```json
{ "type": "canvas", "width": 104, "height": 104, "id": "gauge", "shapes": [
  { "type": "arc",  "x": 52, "y": 56, "r": 40, "start": -120, "end": 120, "color": "faint",  "width": 6 },
  { "type": "arc",  "x": 52, "y": 56, "r": 40, "start": -120, "end": 30,  "color": "accent", "width": 6 },
  { "type": "text", "x": 52, "y": 56, "text": "62", "size": 24, "anchor": "center", "bold": true } ] }
```

Animación: enviar un árbol nuevo por frame (≈30/s como máximo) **solo mientras algo se mueve**.

## Interacción

- Los clics llegan por stdin como `{"type":"event","id":"approve","kind":"click"}`. No hay WebSocket desde la UI.
- `id` estables entre redibujados. Convención: `<módulo>:<acción>[:<id>]`, por ejemplo `agents:approve:abc123`.
- Acciones destructivas: siempre un segundo paso (un botón que cambia a "¿Seguro?" o una confirmación en la page).
- Abrir algo externo: mensaje `open` (URL, archivo o carpeta). Copiar: `copy`.

## Checklist antes de desplegar un plugin

- [ ] Pasa el checker de la skill `fenn-plugin` sin errores.
- [ ] El tile se lee bien en `small` y `wide` (o el tamaño declarado).
- [ ] Probado en tema claro y oscuro.
- [ ] Sin envíos mientras no hay cambios (revisar CPU en reposo).
- [ ] Datos y config en `FENN_DATA_DIR`, secretos en Credential Manager.
