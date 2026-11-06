"""Shared library imported by every Fenn plugin in this repo.

Subpackages:
- `core.protocol`: builders for Fenn's stdio JSON-Lines protocol + theme tokens.
- `core.contracts`: Room v6 payloads (`payload`) and engine/plugin DTOs (`schemas`).
- `core.phone`: connection and delivery to the Android Minimal Launcher.
- `core.brain`: local Ollama inference.
- `core.agents`: Claude / Codex / Gemini session parsers and the agent monitor plugin.
- `core.mail`: placeholder for the IMAP scanner.
"""
