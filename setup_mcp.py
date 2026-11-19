#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instalador Universal 1-Clique do Circle Community MCP (`circle-community`).
100% compatível em paralelo com:
  - Flow Studio MCP (9333/9334)
  - Adobe Podcast MCP (9343/9344)
  - AI Studio Voice MCP (9353/9354)
  - Circle Community MCP (9363/9364)
Configura automaticamente:
  - Google Antigravity (~/.gemini/config/mcp_config.json + ~/.gemini/antigravity/mcp_config.json + Skill global circle-community)
  - Claude Code (~/.claude.json + ~/.claude/skills/circle-community)
  - Cursor (~/.cursor/mcp.json)
"""

import json
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MCP_SERVER_SCRIPT = str(BASE_DIR / "circle_mcp_server.py")
SKILL_SRC = BASE_DIR / "SKILL.md"
PYTHON_EXE = sys.executable


def merge_mcp_json(file_path: Path):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if file_path.exists():
        try:
            content = file_path.read_text(encoding="utf-8").strip()
            if content:
                data = json.loads(content)
        except Exception:
            data = {}

    if not isinstance(data, dict):
        data = {}
    mcp_servers = data.setdefault("mcpServers", {})
    mcp_servers["circle-community"] = {
        "command": PYTHON_EXE,
        "args": [MCP_SERVER_SCRIPT],
    }
    file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      [OK] MCP 'circle-community' registrado em: {file_path}")


def configure_all_agents():
    print("[1/2] Registrando servidor MCP 'circle-community' nos agentes (Antigravity, Claude Code, Cursor)...")
    home = Path.home()

    merge_mcp_json(home / ".gemini" / "config" / "mcp_config.json")
    merge_mcp_json(home / ".gemini" / "antigravity" / "mcp_config.json")

    claude_global = home / ".claude.json"
    if claude_global.exists():
        merge_mcp_json(claude_global)

    merge_mcp_json(home / ".cursor" / "mcp.json")

    print("[2/2] Instalando Skill Global 'circle-community'...")
    if SKILL_SRC.exists():
        for dest_dir in (
            home / ".gemini" / "config" / "skills" / "circle-community",
            home / ".gemini" / "antigravity" / "skills" / "circle-community",
            home / ".claude" / "skills" / "circle-community",
        ):
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SKILL_SRC, dest_dir / "SKILL.md")
            print(f"      [OK] Skill instalada em: {dest_dir / 'SKILL.md'}")


if __name__ == "__main__":
    print("=" * 74)
    print("  INSTALADOR UNIVERSAL - CIRCLE COMMUNITY MCP (PORTAS 9363 / 9364)")
    print("=" * 74)
    configure_all_agents()
    print("\n[SUCESSO] Circle Community MCP instalado e registrado com sucesso!")
