> **Archivado.** Este diseño asumía HTML/CSS/JS, pero Fenn no renderiza HTML.
> La versión vigente es [../design-system.md](../design-system.md).

### 1. Variables globales y Fundamentos de Estilo (Design Tokens)

Configura este bloque en tu CSS global para garantizar que toda la interfaz sea coherente, oscura y mantenga el desenfoque tipo cristal:

```css
:root {
  /* Fondos con profundidad y transparencia */
  --bg-island: rgba(13, 13, 13, 0.82);
  --bg-card: rgba(255, 255, 255, 0.04);
  --bg-card-hover: rgba(255, 255, 255, 0.07);
  --bg-input: rgba(0, 0, 0, 0.35);

  /* Bordes de cristal sutiles */
  --border-subtle: 1px solid rgba(255, 255, 255, 0.08);
  --border-focus: 1px solid rgba(255, 255, 255, 0.22);

  /* Efecto de desenfoque nativo */
  --backdrop-blur: blur(20px) saturate(180%);

  /* Tipografías y tamaños */
  --font-stack: "Segoe UI Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "Cascadia Code", "Fira Code", Consolas, monospace;
  --text-primary: #ededed;
  --text-secondary: #909090;
  --text-muted: #555555;

  /* Estados y acentos */
  --accent-color: #3b82f6; /* Puede sobreescribirse dinámicamente */
  --status-active: #22c55e;
  --status-waiting: #f59e0b;
  --status-error: #ef4444;

  /* Geometría */
  --radius-pill: 9999px;
  --radius-card: 12px;
  --radius-inner: 8px;
}

```

---

### 2. Estructura y Código del Nivel 1: Pastilla (Pill)

La vista contraída debe ser ultracompacta, no romper el flujo de la pantalla y reflejar actividad mediante microanimaciones.

#### HTML

```html
<div class="island-pill">
  <span class="status-dot pulsing"></span>
  <span class="pill-icon">⚡</span>
  <span class="pill-label">Claude</span>
  <span class="pill-separator">·</span>
  <span class="pill-status">Refactoring...</span>
</div>

```

#### CSS

```css
.island-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  padding: 0 12px;
  background: var(--bg-island);
  backdrop-filter: var(--backdrop-blur);
  border: var(--border-subtle);
  border-radius: var(--radius-pill);
  font-family: var(--font-stack);
  font-size: 11px;
  color: var(--text-primary);
  user-select: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.island-pill:hover {
  background: rgba(25, 25, 25, 0.9);
  border-color: rgba(255, 255, 255, 0.16);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--status-active);
}

.status-dot.pulsing {
  box-shadow: 0 0 8px var(--status-active);
  animation: pulse-ring 1.8s infinite cubic-bezier(0.4, 0, 0.6, 1);
}

.pill-separator {
  color: var(--text-muted);
}

.pill-status {
  color: var(--text-secondary);
}

@keyframes pulse-ring {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.9); }
}

```

---

### 3. Estructura y Código del Nivel 2: Mosaico en la Cuadrícula (Tile 2x1)

El tile dentro del notch debe condensar la métrica principal y presentar un estado de interacción rápido.

#### HTML

```html
<div class="tool-tile">
  <header class="tile-header">
    <div class="tile-title-group">
      <div class="tile-icon">⌘</div>
      <span class="tile-name">AI Control</span>
    </div>
    <span class="tile-badge badge-warning">Aprobación</span>
  </header>

  <main class="tile-body">
    <div class="tile-metric">pytest tests/</div>
    <div class="tile-detail">Esperando confirmación en terminal</div>
  </main>

  <footer class="tile-footer">
    <button class="tile-action action-secondary">Rechazar</button>
    <button class="tile-action action-primary">Aprobar</button>
  </footer>
</div>

```

#### CSS

```css
.tool-tile {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 240px;
  height: 120px;
  padding: 12px;
  background: var(--bg-card);
  backdrop-filter: var(--backdrop-blur);
  border: var(--border-subtle);
  border-radius: var(--radius-card);
  font-family: var(--font-stack);
  box-sizing: border-box;
  transition: transform 0.15s ease, background 0.15s ease;
}

.tool-tile:hover {
  background: var(--bg-card-hover);
  border-color: rgba(255, 255, 255, 0.14);
}

.tile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tile-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tile-icon {
  font-size: 14px;
}

.tile-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.tile-badge {
  font-size: 9px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: var(--radius-pill);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.badge-warning {
  background: rgba(245, 158, 11, 0.15);
  color: var(--status-waiting);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.tile-metric {
  font-family: var(--font-mono);
  font-size: 13px;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 4px;
}

.tile-detail {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tile-footer {
  display: flex;
  gap: 8px;
}

.tile-action {
  flex: 1;
  padding: 4px 0;
  font-size: 11px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  border: none;
  transition: opacity 0.15s;
}

.tile-action:hover {
  opacity: 0.85;
}

.action-primary {
  background: var(--accent-color);
  color: #fff;
}

.action-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}

```

---

### 4. Estructura y Código del Nivel 3: Panel Extendido (Drawer / Modal)

El panel que se abre al hacer clic soporta visualización detallada, listas de eventos y terminales compactas.

#### HTML

```html
<div class="tool-panel">
  <!-- Cabecera -->
  <header class="panel-header">
    <div class="panel-title">
      <span class="icon">⌘</span>
      <h3>AI Session — Claude Code</h3>
    </div>
    <div class="panel-controls">
      <span class="chip">Work</span>
      <button class="btn-icon">✕</button>
    </div>
  </header>

  <!-- Contenido / Timeline -->
  <section class="panel-body">
    <div class="event-row">
      <div class="event-indicator success"></div>
      <div class="event-content">
        <div class="event-title">Read workspace config</div>
        <div class="event-meta">11:02:14 · 12ms</div>
      </div>
    </div>

    <div class="event-row">
      <div class="event-indicator active"></div>
      <div class="event-content">
        <div class="event-title">File modified: <code>src/api/routes.py</code></div>
        <div class="event-meta">11:02:40 · Diff +45 -12</div>
      </div>
    </div>

    <!-- Bloque de código / Acción interactiva -->
    <div class="code-preview-block">
      <div class="code-header">
        <span>Terminal Execution Request</span>
        <span class="code-env">bash</span>
      </div>
      <pre class="code-content"><code>pytest tests/test_auth.py --verbose</code></pre>
    </div>
  </section>

  <!-- Acciones inferiores fijas -->
  <footer class="panel-footer">
    <button class="btn btn-outline">Rechazar (Esc)</button>
    <button class="btn btn-primary">Aprobar y Ejecutar (Enter)</button>
  </footer>
</div>

```

#### CSS

```css
.tool-panel {
  width: 440px;
  max-height: 520px;
  display: flex;
  flex-direction: column;
  background: var(--bg-island);
  backdrop-filter: var(--backdrop-blur);
  border: var(--border-subtle);
  border-radius: var(--radius-card);
  font-family: var(--font-stack);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
  overflow: hidden;
}

/* Cabecera */
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: var(--border-subtle);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-title h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chip {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary);
}

.btn-icon {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  font-size: 12px;
}

/* Cuerpo y Eventos */
.panel-body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-body::-webkit-scrollbar {
  width: 4px;
}

.panel-body::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}

.event-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12px;
}

.event-indicator {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}

.event-indicator.success { background: var(--status-active); }
.event-indicator.active { background: var(--status-waiting); }

.event-content {
  flex: 1;
}

.event-title {
  color: var(--text-primary);
}

.event-title code {
  font-family: var(--font-mono);
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 4px;
  border-radius: 4px;
  font-size: 11px;
}

.event-meta {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
}

/* Bloque interactivo de código */
.code-preview-block {
  margin-top: 4px;
  background: var(--bg-input);
  border: var(--border-subtle);
  border-radius: var(--radius-inner);
  overflow: hidden;
}

.code-header {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  font-size: 10px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.02);
  border-bottom: var(--border-subtle);
}

.code-env {
  text-transform: uppercase;
  color: var(--text-muted);
}

.code-content {
  margin: 0;
  padding: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: #38bdf8;
  overflow-x: auto;
}

/* Pie / Acciones */
.panel-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: var(--border-subtle);
  background: rgba(0, 0, 0, 0.2);
}

.btn {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.15s ease;
}

.btn-primary {
  background: var(--accent-color);
  color: #fff;
}

.btn-outline {
  background: transparent;
  border: var(--border-subtle);
  color: var(--text-secondary);
}

.btn:hover {
  filter: brightness(1.15);
}

```

---

### 5. Guía de Renderizado Dinámico con JavaScript

Para mantener desacoplada la interfaz del motor de Python por WebSocket, utiliza una función controladora que actualice únicamente los nodos necesarios sin redibujar todo el DOM:

```javascript
// Listener de WebSocket desde tu backend FastAPI
const socket = new WebSocket("ws://localhost:8765/ws");

socket.onmessage = (event) => {
  const data = JSON.parse(event.data);
  renderModule(data);
};

function renderModule(payload) {
  const { module, pill, tile, panel } = payload;

  // 1. Actualizar Pill
  if (pill) {
    const pillElement = document.getElementById(`pill-${module}`);
    if (pillElement) {
      pillElement.querySelector(".pill-label").textContent = pill.text;
      const dot = pillElement.querySelector(".status-dot");
      dot.className = `status-dot ${pill.status === "running" ? "pulsing" : ""}`;
    }
  }

  // 2. Actualizar Tile
  if (tile) {
    const tileElement = document.getElementById(`tile-${module}`);
    if (tileElement) {
      tileElement.querySelector(".tile-metric").textContent = tile.metric;
      tileElement.querySelector(".tile-detail").textContent = tile.detail;
    }
  }

  // 3. Emitir acción de regreso a Python sin intermediarios
  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.onclick = (e) => {
      const actionName = e.target.getAttribute("data-action");
      socket.send(JSON.stringify({ module, action: actionName, timestamp: Date.now() }));
    };
  });
}

```