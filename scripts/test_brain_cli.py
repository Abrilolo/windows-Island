"""CLI utility to test `OllamaBrain` extraction and inspect the resulting Room v6 JSON."""

from __future__ import annotations

import json
from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from brain.ollama_client import OllamaBrain


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sample = (
        " ".join(sys.argv[1:]).strip()
        if len(sys.argv) > 1
        else "Comí 200g de pollo, gasté 120 en café y recuérdame pagar la luz a las 18:00"
    )

    brain = OllamaBrain()
    installed = brain.list_installed_models()
    if installed and brain.model not in installed:
        print(
            f"ℹ️ Modelo '{brain.model}' no encontrado, usando modelo instalado: '{installed[0]}'"
        )
        brain.model = installed[0]
    elif not installed:
        print(
            "⚠️ Aún no tienes ningún modelo descargado en Ollama.\n"
            "   Corre en tu PowerShell:\n"
            '   & "$env:LOCALAPPDATA\\Programs\\Ollama\\ollama.exe" pull qwen2.5:3b\n'
        )

    print(f"=== Probando OllamaBrain ({brain.base_url} | modelo: {brain.model}) ===")
    print(f"Entrada: {sample}\n")

    outcome = brain.analyze_text(sample)
    if outcome.used_fallback:
        print(f"⚠️ MODO FALLBACK ACTIVADO: {outcome.error_message}\n")
    else:
        print("✨ Extracción estructurada exitosa:\n")

    print("--- Vista previa en Nook ---")
    for line in outcome.payload.format_preview_lines():
        print(f"  {line}")

    print("\n--- Payload JSON para Minimal Launcher (Room v6) ---")
    print(
        json.dumps(
            outcome.payload.to_launcher_dict(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
