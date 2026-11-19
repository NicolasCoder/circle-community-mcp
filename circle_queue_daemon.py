#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
circle-community — Central Queue Daemon (`circle_queue_daemon.py`)
==================================================================
  - Chrome CDP Port : 9363 (C:\\circle-mcp-profile)
  - HTTP Queue Port : 9364
  - Ghost Mode      : SW_HIDE + WS_EX_TOOLWINDOW + -32000,-32000 + ITaskbarList::DeleteTab (Zero Tray, Zero Rastro)
"""

import asyncio
import importlib
import json
import os
import sqlite3
import sys
import uuid
from collections import deque
from datetime import datetime
from aiohttp import web
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import circleapi as core_api

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = int(os.environ.get("CIRCLE_DAEMON_PORT", "9364"))
PRIMARY_PROFILE_DIR = core_api._obter_diretorio_perfil_base("conta_1")
DB_PATH = os.path.join(PRIMARY_PROFILE_DIR, "circle_queue.db")


def init_db():
    os.makedirs(PRIMARY_PROFILE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            action TEXT,
            payload_json TEXT,
            result_json TEXT,
            status TEXT,
            error TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def db_log_action(action: str, payload: dict, result: dict, status: str = "completed", error: str = ""):
    try:
        job_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO jobs (job_id, action, payload_json, result_json, status, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                action,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False)[:8000],
                status,
                error,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


class CircleMCPDaemon:
    def __init__(self):
        self.browser_lock = asyncio.Lock()
        self.playwright = None
        self.browser = None
        self.page = None
        self.config = core_api.carregar_config()
        self.invisivel = True  # Agora com login concluído, padrão é 100% Modo Fantasma Invisível!
        self.recent_network = deque(maxlen=60)
        self._attached_pages = set()

    async def start(self):
        self.playwright = await async_playwright().start()

    async def stop(self):
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass

    def _attach_network_sniffer(self, page):
        if id(page) in self._attached_pages:
            return
        self._attached_pages.add(id(page))

        async def on_response(resp):
            try:
                u = resp.url
                kws = (
                    core_api.carregar_seletores()
                    .get("api_endpoints", {})
                    .get("sniffer_keywords", ["internal_api", "/api/v1/", "/spaces", "/posts", "/chat"])
                )
                if any(k in u.lower() for k in kws):
                    preview = ""
                    try:
                        if "json" in (resp.headers.get("content-type") or "").lower():
                            preview = (await resp.text())[:500]
                    except Exception:
                        pass
                    self.recent_network.append(
                        {
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "method": resp.request.method,
                            "status": resp.status,
                            "url": u[:240],
                            "preview": preview,
                        }
                    )
            except Exception:
                pass

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

    async def ensure_browser_and_page(self, force_visible: bool = None):
        profile_atual = core_api.obter_diretorio_perfil()

        if not self.browser or not self.browser.is_connected() or (self.page and self.page.is_closed()):
            self.browser = None
            self.page = None
            try:
                self.browser = await self.playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{core_api.CHROME_PORT}"
                )
            except Exception:
                vis_init = False if force_visible is True else self.invisivel
                core_api.iniciar_chrome_isolado(
                    invisivel=vis_init, porta=core_api.CHROME_PORT, profile_dir=profile_atual
                )
                for _ in range(22):
                    await asyncio.sleep(1.0)
                    try:
                        self.browser = await self.playwright.chromium.connect_over_cdp(
                            f"http://127.0.0.1:{core_api.CHROME_PORT}"
                        )
                        break
                    except Exception:
                        pass
                if not self.browser:
                    raise RuntimeError(f"Nao foi possivel conectar ao Chrome na porta {core_api.CHROME_PORT}")

        ctx = self.browser.contexts[0]
        circle_pages = [p for p in ctx.pages if "circle.so" in p.url]
        valid_pages = [
            p
            for p in ctx.pages
            if not p.url.startswith("devtools://") and not p.url.startswith("chrome-extension://")
        ]
        self.page = (
            circle_pages[0]
            if circle_pages
            else (valid_pages[0] if valid_pages else (ctx.pages[0] if ctx.pages else await ctx.new_page()))
        )
        self._attach_network_sniffer(self.page)
        await core_api.injetar_bypass_e_silencio(self.page)

        if force_visible is not None:
            self.invisivel = not force_visible
            await core_api.posicionar_janela_chrome(self.page, invisivel=self.invisivel)
        elif self.invisivel:
            # Garante que permanece oculto em SW_HIDE + WS_EX_TOOLWINDOW
            core_api.controlar_visibilidade_janela_win32(visivel=False, porta=core_api.CHROME_PORT)

        if self.page.url in ("about:blank", "", "chrome://newtab/"):
            await self.page.goto("https://engenheiros-de-video.circle.so/feed", wait_until="domcontentloaded")
            await asyncio.sleep(1.5)

        params = await core_api.obter_parametros_pagina(self.page)
        logado = bool(params.get("loggedIn"))
        return self.page, params, logado


daemon = CircleMCPDaemon()


async def handle_health(request: web.Request):
    return web.json_response(
        {
            "ok": True,
            "service": "circle-community",
            "prefix": "circle",
            "chrome_port": core_api.CHROME_PORT,
            "daemon_port": DAEMON_PORT,
            "profile_dir": PRIMARY_PROFILE_DIR,
            "invisivel": daemon.invisivel,
            "login_completed_flag": core_api.ja_fez_login_inicial(PRIMARY_PROFILE_DIR),
        }
    )


async def handle_status(request: web.Request):
    async with daemon.browser_lock:
        try:
            page, params, logado = await daemon.ensure_browser_and_page(force_visible=None)
            return web.json_response(
                {
                    "ok": True,
                    "service": "circle-community",
                    "chrome_port": core_api.CHROME_PORT,
                    "daemon_port": DAEMON_PORT,
                    "profile_dir": PRIMARY_PROFILE_DIR,
                    "invisivel": daemon.invisivel,
                    "logged_in": logado,
                    "page_params": params,
                    "recent_network_count": len(daemon.recent_network),
                }
            )
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_browser_show(request: web.Request):
    async with daemon.browser_lock:
        page, params, logado = await daemon.ensure_browser_and_page(force_visible=True)
        return web.json_response(
            {
                "ok": True,
                "visible": True,
                "invisivel": False,
                "url": page.url,
                "logged_in": logado,
                "message": "Janela do Chrome (porta 9363) visível na tela (120, 80).",
            }
        )


async def handle_browser_hide(request: web.Request):
    async with daemon.browser_lock:
        page, params, logado = await daemon.ensure_browser_and_page(force_visible=False)
        if logado and params.get("origin"):
            core_api.marcar_login_concluido(PRIMARY_PROFILE_DIR, community_origin=params["origin"])
        return web.json_response(
            {
                "ok": True,
                "visible": False,
                "invisivel": True,
                "url": page.url,
                "logged_in": logado,
                "message": "Janela do Chrome (porta 9363) ocultada 100% em Modo Fantasma (SW_HIDE + WS_EX_TOOLWINDOW + -32000,-32000 + Sem Taskbar).",
            }
        )


async def handle_browser_login(request: web.Request):
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass
    url = data.get("url") or "https://login.circle.so/"
    async with daemon.browser_lock:
        page, params, logado = await daemon.ensure_browser_and_page(force_visible=True)
        if url and page.url != url and not logado:
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1.5)
            params = await core_api.obter_parametros_pagina(page)
            logado = bool(params.get("loggedIn"))
        return web.json_response(
            {
                "ok": True,
                "visible": True,
                "logged_in": logado,
                "url": page.url,
                "profile_dir": PRIMARY_PROFILE_DIR,
            }
        )


async def _run_circle_fn(request: web.Request, action_name: str, fn):
    data = await request.json() if request.can_read_body else {}
    async with daemon.browser_lock:
        try:
            page, _, _ = await daemon.ensure_browser_and_page(force_visible=None)
            res = await fn(page, data)
            db_log_action(action_name, data, res)
            return web.json_response(res)
        except Exception as e:
            diag = await core_api.coletar_diagnostico_pagina(
                daemon.page, motivo=str(e), recent_network=list(daemon.recent_network)
            )
            return web.json_response({"ok": False, "error": str(e), "diagnostics": diag}, status=500)


async def handle_list_spaces(request: web.Request):
    return await _run_circle_fn(
        request,
        "list_spaces",
        lambda page, d: core_api.listar_spaces_e_chats(page, community_url=d.get("community_url", "")),
    )


async def handle_get_chat_messages(request: web.Request):
    return await _run_circle_fn(
        request,
        "get_chat_messages",
        lambda page, d: core_api.obter_mensagens_chat(
            page, chat_url_or_slug=d.get("chat_url_or_slug", "papo"), limit=int(d.get("limit", 40))
        ),
    )


async def handle_send_chat_message(request: web.Request):
    return await _run_circle_fn(
        request,
        "send_chat_message",
        lambda page, d: core_api.enviar_mensagem_chat(
            page,
            message=d.get("message", ""),
            chat_url_or_slug=d.get("chat_url_or_slug", "papo"),
            attachment_path=d.get("attachment_path", ""),
        ),
    )


async def handle_get_posts(request: web.Request):
    return await _run_circle_fn(
        request,
        "get_posts",
        lambda page, d: core_api.obter_posts_space(
            page, space_url_or_slug=d.get("space_url_or_slug", ""), limit=int(d.get("limit", 15))
        ),
    )


async def handle_get_post_comments(request: web.Request):
    return await _run_circle_fn(
        request,
        "get_post_comments",
        lambda page, d: core_api.obter_comentarios_post(
            page, post_id_or_url=d.get("post_id_or_url", ""), page_num=int(d.get("page_num", 1))
        ),
    )


async def handle_create_post(request: web.Request):
    return await _run_circle_fn(
        request,
        "create_post",
        lambda page, d: core_api.criar_post_space(
            page,
            space_url_or_slug=d.get("space_url_or_slug", ""),
            title=d.get("title", ""),
            body=d.get("body", ""),
            attachment_path=d.get("attachment_path", ""),
        ),
    )


async def handle_edit_post(request: web.Request):
    return await _run_circle_fn(
        request,
        "edit_post",
        lambda page, d: core_api.editar_post_space(
            page,
            space_url_or_slug=d.get("space_url_or_slug", ""),
            post_id_or_slug=d.get("post_id_or_slug", ""),
            title=d.get("title", ""),
            body=d.get("body", ""),
            attachment_path=d.get("attachment_path", ""),
            keep_existing_image_signed_id=d.get("keep_existing_image_signed_id", ""),
        ),
    )


async def handle_comment_post(request: web.Request):
    return await _run_circle_fn(
        request,
        "comment_post",
        lambda page, d: core_api.comentar_post(
            page, post_url=d.get("post_url", ""), comment_text=d.get("comment_text", "")
        ),
    )


async def handle_like_post(request: web.Request):
    return await _run_circle_fn(
        request,
        "like_post",
        lambda page, d: core_api.curtir_post(page, post_id_or_url=d.get("post_id_or_url", "")),
    )


async def handle_search(request: web.Request):
    return await _run_circle_fn(
        request,
        "search",
        lambda page, d: core_api.buscar_na_comunidade(
            page,
            query=d.get("query", ""),
            include_chat=bool(d.get("include_chat", True)),
            limit=int(d.get("limit", 25)),
        ),
    )


async def handle_list_members(request: web.Request):
    return await _run_circle_fn(
        request,
        "list_members",
        lambda page, d: core_api.listar_membros_comunidade(page, limit=int(d.get("limit", 30))),
    )


async def handle_get_member_profile(request: web.Request):
    return await _run_circle_fn(
        request,
        "get_member_profile",
        lambda page, d: core_api.obter_perfil_membro(page, public_uid=d.get("public_uid", "")),
    )


async def handle_get_notifications(request: web.Request):
    return await _run_circle_fn(
        request,
        "get_notifications",
        lambda page, d: core_api.obter_notificacoes(
            page, unread_only=bool(d.get("unread_only", False)), limit=int(d.get("limit", 25))
        ),
    )


async def handle_diagnose(request: web.Request):
    data = await request.json() if request.can_read_body else {}
    reason = data.get("reason", "manual_diagnose")
    take_ss = bool(data.get("take_screenshot", True))
    async with daemon.browser_lock:
        page, _, _ = await daemon.ensure_browser_and_page(force_visible=None)
        diag = await core_api.coletar_diagnostico_pagina(
            page, motivo=reason, recent_network=list(daemon.recent_network), take_screenshot=take_ss
        )
        return web.json_response({"ok": True, "diagnostics": diag})


async def handle_update_selectors(request: web.Request):
    data = await request.json()
    updated = core_api.atualizar_seletores(data.get("selectors", data))
    return web.json_response({"ok": True, "selectors": updated})


async def handle_reload(request: web.Request):
    importlib.reload(core_api)
    daemon.config = core_api.carregar_config()
    return web.json_response({"ok": True, "reloaded": True})


async def on_startup(app: web.Application):
    init_db()
    await daemon.start()


async def on_cleanup(app: web.Application):
    await daemon.stop()


def create_app() -> web.Application:
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/browser/show", handle_browser_show)
    app.router.add_post("/browser/hide", handle_browser_hide)
    app.router.add_post("/browser/login", handle_browser_login)
    app.router.add_post("/circle/list_spaces", handle_list_spaces)
    app.router.add_post("/circle/get_chat_messages", handle_get_chat_messages)
    app.router.add_post("/circle/send_chat_message", handle_send_chat_message)
    app.router.add_post("/circle/get_posts", handle_get_posts)
    app.router.add_post("/circle/get_post_comments", handle_get_post_comments)
    app.router.add_post("/circle/create_post", handle_create_post)
    app.router.add_post("/circle/edit_post", handle_edit_post)
    app.router.add_post("/circle/comment_post", handle_comment_post)
    app.router.add_post("/circle/like_post", handle_like_post)
    app.router.add_post("/circle/search", handle_search)
    app.router.add_post("/circle/list_members", handle_list_members)
    app.router.add_post("/circle/get_member_profile", handle_get_member_profile)
    app.router.add_post("/circle/get_notifications", handle_get_notifications)
    app.router.add_post("/diagnose", handle_diagnose)
    app.router.add_post("/selectors/update", handle_update_selectors)
    app.router.add_post("/reload", handle_reload)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=DAEMON_HOST, port=DAEMON_PORT, print=None)
