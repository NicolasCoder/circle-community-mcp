#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
circle-community — FastMCP Server (`circle_mcp_server.py`)
==========================================================
Servidor MCP Oficial para Comunidades Circle.so (ex: Engenheiros de Vídeo):
  - Porta Chrome CDP Isolado : 9363 (C:\\circle-mcp-profile)
  - Porta Daemon Fila Central: 9364
  - Modo Fantasma Invisível  : SW_HIDE + WS_EX_TOOLWINDOW + -32000,-32000 + ITaskbarList::DeleteTab (Zero Tray, Zero Rastro)
  - 18 Tools Expostas (7 Famílias):
      1. `circle_list_spaces`
      2. `circle_get_chat_messages`
      3. `circle_send_chat_message`
      4. `circle_get_posts`
      5. `circle_get_post_comments`
      6. `circle_create_post`
      7. `circle_comment_post`
      8. `circle_like_post`
      9. `circle_search`
     10. `circle_list_members`
     11. `circle_get_member_profile`
     12. `circle_get_notifications`
     13. `circle_hide_browser`
     14. `circle_show_browser`
     15. `circle_login_browser`
     16. `circle_status`
     17. `circle_diagnose`
     18. `circle_update_selectors` & `circle_reload_daemon`
"""

import asyncio
import os
import subprocess
import sys
from typing import Any, Dict, Optional
import aiohttp
from mcp.server.fastmcp import FastMCP

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAEMON_SCRIPT = os.path.join(BASE_DIR, "circle_queue_daemon.py")
DAEMON_PORT = int(os.environ.get("CIRCLE_DAEMON_PORT", "9364"))
DAEMON_URL = f"http://127.0.0.1:{DAEMON_PORT}"

mcp = FastMCP("circle-community")


async def ensure_daemon_running() -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=3)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(f"{DAEMON_URL}/health") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass

    pythonw_exe = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = sys.executable

    if os.name == "nt":
        cmd_str = f'"{pythonw_exe}" "{DAEMON_SCRIPT}"'
        ps_cmd = (
            f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{CommandLine='{cmd_str}'; CurrentDirectory='{BASE_DIR}'}} | Out-Null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            [sys.executable, DAEMON_SCRIPT],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(25):
            await asyncio.sleep(0.5)
            try:
                async with session.get(f"{DAEMON_URL}/health") as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception:
                pass

    raise RuntimeError(f"Nao foi possivel iniciar ou conectar ao Circle MCP Daemon na porta {DAEMON_PORT}.")


async def daemon_request(
    method: str, path: str, payload: Optional[dict] = None, timeout_sec: float = 120.0
) -> dict:
    await ensure_daemon_running()
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        url = f"{DAEMON_URL}{path}"
        if method.upper() == "GET":
            async with session.get(url) as resp:
                return await resp.json()
        else:
            async with session.post(url, json=payload or {}) as resp:
                return await resp.json()


# 1. Comunidades & Spaces
@mcp.tool()
async def circle_list_spaces(community_url: str = "") -> Dict[str, Any]:
    """
    Lista a comunidade do Circle.so logada (`/internal_api/communities`), todos os Spaces de postagem,
    cursos, eventos e salas de chat (`/internal_api/spaces`) e todas as DMs (`/internal_api/chat_rooms`).
    """
    return await daemon_request("POST", "/circle/list_spaces", {"community_url": community_url})


# 2. Chat Ao Vivo & DMs
@mcp.tool()
async def circle_get_chat_messages(chat_url_or_slug: str = "papo", limit: int = 40) -> Dict[str, Any]:
    """
    Puxa as mensagens em tempo real do chat da comunidade (padrão: 'papo' -> uuid 9deb17c9-e35a-448e-8322-164241947ef8)
    ou de qualquer DM (passando o nome do contato ou uuid da sala).
    """
    return await daemon_request(
        "POST",
        "/circle/get_chat_messages",
        {"chat_url_or_slug": chat_url_or_slug, "limit": limit},
    )


@mcp.tool()
async def circle_send_chat_message(
    message: str,
    chat_url_or_slug: str = "papo",
    attachment_path: str = "",
) -> Dict[str, Any]:
    """
    Envia uma mensagem no chat da comunidade (padrão: 'papo') ou em uma DM (passando nome/UUID da conversa).
    Usa `POST /internal_api/chat_rooms/<uuid>/messages` com fallback automático para o editor ProseMirror.
    """
    return await daemon_request(
        "POST",
        "/circle/send_chat_message",
        {
            "message": message,
            "chat_url_or_slug": chat_url_or_slug,
            "attachment_path": attachment_path,
        },
    )


# 3. Feed, Postagens, Comentários & Likes
@mcp.tool()
async def circle_get_posts(space_url_or_slug: str = "", limit: int = 15) -> Dict[str, Any]:
    """
    Puxa as postagens recentes do Feed Geral (`space_url_or_slug=""`) ou de qualquer Space específico
    (ex: 'edicao', 'ia', 'motion' [Oportunidades], 'negocios', 'get-brolls', 'get-brolls-hub', 'clones',
    'hyperframes', 'projetos', 'conteudos', 'eventos', 'apresente-se', 'boas-vindas').
    """
    return await daemon_request(
        "POST",
        "/circle/get_posts",
        {"space_url_or_slug": space_url_or_slug, "limit": limit},
    )


@mcp.tool()
async def circle_get_post_comments(post_id_or_url: str, page_num: int = 1) -> Dict[str, Any]:
    """
    Puxa todos os comentários de um post específico (passando o ID numérico do post ex: '38565655' ou URL/slug).
    """
    return await daemon_request(
        "POST",
        "/circle/get_post_comments",
        {"post_id_or_url": post_id_or_url, "page_num": page_num},
    )


@mcp.tool()
async def circle_create_post(
    space_url_or_slug: str,
    title: str,
    body: str,
    attachment_path: str = "",
) -> Dict[str, Any]:
    """
    Cria e publica uma nova postagem em qualquer Space da comunidade Circle.so (ex: `space_url_or_slug="ia"`, `"edicao"`, `"projetos"`).
    Usa `POST /internal_api/spaces/<id>/posts` (TipTap JSON) com fallback para o editor ProseMirror.
    """
    return await daemon_request(
        "POST",
        "/circle/create_post",
        {
            "space_url_or_slug": space_url_or_slug,
            "title": title,
            "body": body,
            "attachment_path": attachment_path,
        },
    )


@mcp.tool()
async def circle_edit_post(
    space_url_or_slug: str,
    post_id_or_slug: str,
    title: str = "",
    body: str = "",
    attachment_path: str = "",
    keep_existing_image_signed_id: str = "",
) -> Dict[str, Any]:
    """
    Edita uma postagem existente in-place via `PUT /internal_api/spaces/<space_id>/posts/<post_id>`
    sem criar post duplicado! Preserva a imagem de capa e converte URLs e menções `@[Nome](url)` em links clicáveis do TipTap.
    """
    return await daemon_request(
        "POST",
        "/circle/edit_post",
        {
            "space_url_or_slug": space_url_or_slug,
            "post_id_or_slug": post_id_or_slug,
            "title": title,
            "body": body,
            "attachment_path": attachment_path,
            "keep_existing_image_signed_id": keep_existing_image_signed_id,
        },
    )


@mcp.tool()
async def circle_comment_post(post_url: str, comment_text: str) -> Dict[str, Any]:
    """
    Publica um comentário / resposta em um post existente (aceita `post_id` numérico ou URL completa do post).
    """
    return await daemon_request(
        "POST",
        "/circle/comment_post",
        {"post_url": post_url, "comment_text": comment_text},
    )


@mcp.tool()
async def circle_like_post(post_id_or_url: str) -> Dict[str, Any]:
    """
    Curte (dá like) em um post da comunidade Circle.so (`POST /internal_api/posts/<id>/user_likes`).
    """
    return await daemon_request(
        "POST",
        "/circle/like_post",
        {"post_id_or_url": post_id_or_url},
    )


# 4. Busca Global & Radar de Oportunidades/Vagas
@mcp.tool()
async def circle_search(query: str, include_chat: bool = True, limit: int = 25) -> Dict[str, Any]:
    """
    Radar de Busca Global na comunidade Circle.so: busca termos, vagas, freelas, dúvidas ou temas
    simultaneamente nos posts do Feed, no Space de Oportunidades (`/c/motion`) e no Chat Ao Vivo (`Papo`).
    """
    return await daemon_request(
        "POST",
        "/circle/search",
        {"query": query, "include_chat": include_chat, "limit": limit},
    )


# 5. Membros & Networking/Leads
@mcp.tool()
async def circle_list_members(limit: int = 30) -> Dict[str, Any]:
    """
    Lista membros ativos da comunidade Circle.so, contatos de DM e dados de gamificação (`/internal_api/gamification/members`).
    """
    return await daemon_request("POST", "/circle/list_members", {"limit": limit})


@mcp.tool()
async def circle_get_member_profile(public_uid: str) -> Dict[str, Any]:
    """
    Puxa o perfil completo de um membro da comunidade via `/internal_api/profiles/<public_uid>?page_name=profile_view`
    (nome, bio, headline, redes sociais, Instagram, links e localização).
    """
    return await daemon_request("POST", "/circle/get_member_profile", {"public_uid": public_uid})


# 6. Notificações & Menções
@mcp.tool()
async def circle_get_notifications(unread_only: bool = False, limit: int = 25) -> Dict[str, Any]:
    """
    Puxa as notificações da conta no Circle.so (`/internal_api/notifications`): respostas, menções `@`,
    novos posts nos Spaces seguidos e atividades recentes.
    """
    return await daemon_request(
        "POST",
        "/circle/get_notifications",
        {"unread_only": unread_only, "limit": limit},
    )


# 7. Controle Fantasma & Auto-Healing
@mcp.tool()
async def circle_hide_browser() -> Dict[str, Any]:
    """
    Esconde 100% a janela do Google Chrome do Circle MCP (porta 9363) em Modo Fantasma
    (SW_HIDE + WS_EX_TOOLWINDOW + -32000,-32000 + remoção do ícone da Barra de Tarefas, sem System Tray)
    para que nem pareça que está em execução!
    """
    return await daemon_request("POST", "/browser/hide")


@mcp.tool()
async def circle_show_browser() -> Dict[str, Any]:
    """
    Mostra a janela do Google Chrome do Circle MCP (porta 9363) na tela principal (120, 80).
    """
    return await daemon_request("POST", "/browser/show")


@mcp.tool()
async def circle_login_browser(url: str = "https://login.circle.so/") -> Dict[str, Any]:
    """
    Abre e traz para a frente a janela do Google Chrome isolado (porta 9363, perfil C:\\circle-mcp-profile).
    """
    return await daemon_request("POST", "/browser/login", {"url": url})


@mcp.tool()
async def circle_status() -> Dict[str, Any]:
    """
    Retorna o status completo do Circle MCP Daemon (porta 9364) e Chrome CDP (porta 9363).
    """
    return await daemon_request("GET", "/status")


@mcp.tool()
async def circle_diagnose(reason: str = "manual_check", take_screenshot: bool = True) -> Dict[str, Any]:
    """
    Executa o Raio-X de Auto-Healing (DOM + Shadow-DOM + chamadas de rede /internal_api/ + screenshot).
    """
    return await daemon_request("POST", "/diagnose", {"reason": reason, "take_screenshot": take_screenshot})


@mcp.tool()
async def circle_update_selectors(selectors: Dict[str, Any]) -> Dict[str, Any]:
    """
    Atualiza `selectors.json` em tempo real para Auto-Healing.
    """
    return await daemon_request("POST", "/selectors/update", {"selectors": selectors})


@mcp.tool()
async def circle_reload_daemon() -> Dict[str, Any]:
    """
    Recarrega a quente (`importlib.reload`) o módulo `circleapi.py` e `selectors.json` no daemon.
    """
    return await daemon_request("POST", "/reload")


if __name__ == "__main__":
    mcp.run()
