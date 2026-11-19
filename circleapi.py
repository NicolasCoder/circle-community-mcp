#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
circle-community — Core Web-to-MCP Engine (`circleapi.py`)
===========================================================
Arquitetura Blindada (MCP Creator — Connect Anything) especializada para Circle.so:
  1. Native Chrome CDP Engine (Porta 9363 | Perfil C:\\circle-mcp-profile) + Job-Object Detachment
  2. Ghost Off-Screen Total (`SW_HIDE` user32.dll + `WS_EX_TOOLWINDOW` + `-32000,-32000` + `ITaskbarList::DeleteTab` = Zero Rastro Visual e Zero Tray)
  3. Escudo Triplo de Silêncio Absoluto (`--mute-audio` + CDP `setAudioMuted` + WebAudio `ZeroGain`)
  4. Motor Híbrido Circle.so (`In-Page Authenticated Fetch /internal_api/...` + `ProseMirror/TipTap/React Fiber DOM`)
  5. Pacote Completo de 7 Famílias de Funções:
     - Comunidades & Spaces: `listar_spaces_e_chats`
     - Chat Ao Vivo & DMs: `obter_mensagens_chat`, `enviar_mensagem_chat`
     - Feed, Postagens, Comentários & Likes: `obter_posts_space`, `obter_comentarios_post`, `criar_post_space`, `comentar_post`, `curtir_post`
     - Busca Global & Radar de Oportunidades/Vagas: `buscar_na_comunidade`
     - Membros & Networking/Leads: `listar_membros_comunidade`, `obter_perfil_membro`
     - Notificações & Menções: `obter_notificacoes`
     - Controle Fantasma & Auto-Healing: `posicionar_janela_chrome`, `coletar_diagnostico_pagina`
"""

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SELECTORS_PATH = os.path.join(BASE_DIR, "selectors.json")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "accounts.json")
DOM_BYPASS_PATH = os.path.join(BASE_DIR, "dom_bypass.js")
DIAGNOSTICS_DIR = os.path.join(BASE_DIR, "diagnostics")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

CHROME_PORT = int(os.environ.get("CIRCLE_CHROME_PORT", "9363"))
DAEMON_PORT = int(os.environ.get("CIRCLE_DAEMON_PORT", "9364"))

# UUID conhecido da sala de chat principal "Papo" em Engenheiros de Vídeo (descoberto automaticamente também via /internal_api/chat_threads)
DEFAULT_PAPO_CHAT_UUID = "9deb17c9-e35a-448e-8322-164241947ef8"


def carregar_dom_bypass_js() -> str:
    if os.path.exists(DOM_BYPASS_PATH):
        try:
            with open(DOM_BYPASS_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return "window.__MCP_CREATOR_BYPASS__ = window.__MCP_CREATOR_BYPASS__ || {};"


def _obter_diretorio_perfil_base(account_id: str = "conta_1") -> str:
    env_dir = os.environ.get("CIRCLE_PROFILE_DIR")
    if env_dir and account_id in ("", "conta_1", "default"):
        return env_dir
    base = (
        r"C:\circle-mcp-profile"
        if os.name == "nt"
        else os.path.join(os.path.expanduser("~"), ".circle-mcp-profile")
    )
    if not account_id or account_id in ("conta_1", "default"):
        return base
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", account_id.strip().lower())
    return f"{base}-{slug}"


def _criar_registro_conta_padrao(account_id: str = "conta_1", label: str = "Conta Principal Circle") -> dict:
    prof_dir = _obter_diretorio_perfil_base(account_id)
    return {
        "id": account_id,
        "label": label,
        "profile_dir": prof_dir,
        "email": "",
        "display_name": "",
        "community_origin": "https://engenheiros-de-video.circle.so",
        "logged_in": os.path.exists(os.path.join(prof_dir, ".login_completed")),
        "last_checked_at": "",
    }


def carregar_contas() -> dict:
    padrao = {
        "active_account": "conta_1",
        "auto_rotate": False,
        "accounts": {
            "conta_1": _criar_registro_conta_padrao("conta_1", "Conta Principal Circle"),
        },
    }
    dados = padrao
    if os.path.exists(ACCOUNTS_PATH):
        try:
            with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
                lido = json.load(f)
                if isinstance(lido, dict) and isinstance(lido.get("accounts"), dict) and lido["accounts"]:
                    dados = lido
        except Exception:
            pass

    if "conta_1" not in dados["accounts"]:
        dados["accounts"]["conta_1"] = _criar_registro_conta_padrao("conta_1", "Conta Principal Circle")
    if dados.get("active_account") not in dados["accounts"]:
        dados["active_account"] = next(iter(dados["accounts"].keys()))
    return dados


def salvar_contas(dados: dict) -> dict:
    try:
        with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return dados


def obter_conta_ativa() -> dict:
    dados = carregar_contas()
    acc_id = dados.get("active_account", "conta_1")
    return dados["accounts"].get(acc_id) or next(iter(dados["accounts"].values()))


def obter_diretorio_perfil(account_id: str = "") -> str:
    dados = carregar_contas()
    alvo = account_id.strip() if account_id else dados.get("active_account", "conta_1")
    acc = dados["accounts"].get(alvo)
    if acc and acc.get("profile_dir"):
        return acc["profile_dir"]
    return _obter_diretorio_perfil_base(alvo)


def ja_fez_login_inicial(profile_dir: str = "") -> bool:
    alvo = profile_dir or obter_diretorio_perfil()
    return os.path.exists(os.path.join(alvo, ".login_completed"))


def marcar_login_concluido(profile_dir: str = "", community_origin: str = ""):
    alvo = profile_dir or obter_diretorio_perfil()
    os.makedirs(alvo, exist_ok=True)
    with open(os.path.join(alvo, ".login_completed"), "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat())
    dados = carregar_contas()
    for acc in dados["accounts"].values():
        if os.path.normcase(acc.get("profile_dir", "")) == os.path.normcase(alvo):
            acc["logged_in"] = True
            if community_origin:
                acc["community_origin"] = community_origin
    salvar_contas(dados)


def detectar_executavel_chrome() -> str:
    for env_var in ("CIRCLE_CHROME_EXE", "CHROME_EXE", "FLOW_CHROME_EXE"):
        env_chrome = os.environ.get(env_var)
        if env_chrome and os.path.exists(env_chrome):
            return env_chrome

    sistema = platform.system().lower()
    candidatos = []
    if sistema == "windows":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        prog_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        candidatos = [
            os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_files, r"Google\Chrome Beta\Application\chrome.exe"),
        ]
    elif sistema == "darwin":
        candidatos = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:
        for cmd in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
            achado = shutil.which(cmd)
            if achado:
                candidatos.append(achado)

    for c in candidatos:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError("Google Chrome nao encontrado. Defina CIRCLE_CHROME_EXE.")


def carregar_seletores() -> dict:
    if os.path.exists(SELECTORS_PATH):
        try:
            with open(SELECTORS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"selectors": {"target_url": "https://engenheiros-de-video.circle.so/feed"}, "api_endpoints": {}}


def atualizar_seletores(novos_dados: dict) -> dict:
    atual = carregar_seletores()
    for k, v in novos_dados.items():
        if isinstance(v, dict) and k in atual and isinstance(atual[k], dict):
            atual[k].update(v)
        elif not isinstance(v, dict) and k in atual.get("selectors", {}):
            atual["selectors"][k] = v
        else:
            atual[k] = v
    with open(SELECTORS_PATH, "w", encoding="utf-8") as f:
        json.dump(atual, f, indent=2, ensure_ascii=False)
    return atual


def carregar_config() -> dict:
    padrao = {
        "modo_invisivel": True,
        "mute_audio": True,
        "zero_tray": True,
        "timeout_processamento_seg": 120,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                padrao.update(json.load(f))
        except Exception:
            pass
    return padrao


def fechar_chrome_porta(porta: int = CHROME_PORT):
    """Encerra APENAS os processos do Google Chrome iniciados na porta 9363."""
    try:
        import psutil
        raizes = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                nome = (proc.info.get("name") or "").lower()
                if "chrome" in nome:
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if f"--remote-debugging-port={porta}" in cmd and "--type=" not in cmd:
                        raizes.append(proc)
            except Exception:
                pass

        todos = []
        for proc in raizes:
            try:
                for child in proc.children(recursive=True):
                    todos.append(child)
                    try:
                        child.terminate()
                    except Exception:
                        pass
                todos.append(proc)
                proc.terminate()
            except Exception:
                pass
        _, alive = psutil.wait_procs(todos, timeout=3)
        for proc in alive:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        pass


def iniciar_chrome_isolado(invisivel: bool = True, porta: int = CHROME_PORT, profile_dir: str = "", url: str = ""):
    chrome_exe = detectar_executavel_chrome()
    prof = profile_dir or obter_diretorio_perfil()
    os.makedirs(prof, exist_ok=True)
    cfg = carregar_config()
    acc = obter_conta_ativa()
    target_url = url or acc.get("community_origin") or "https://engenheiros-de-video.circle.so/feed"
    pos_arg = "--window-position=-32000,-32000" if invisivel else "--window-position=120,80"

    args_list = [
        f"--remote-debugging-port={porta}",
        f'--user-data-dir="{prof}"' if os.name == "nt" else f"--user-data-dir={prof}",
        "--window-size=1280,860",
        pos_arg,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]
    if cfg.get("mute_audio", True):
        args_list.extend(["--mute-audio", "--autoplay-policy=user-gesture-required"])

    args_list.append(f'"{target_url}"' if os.name == "nt" else target_url)

    if os.name == "nt":
        cmd_str = f'"{chrome_exe}" ' + " ".join(args_list)
        ps_cmd = (
            f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{CommandLine='{cmd_str}'}} | Out-Null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            [chrome_exe] + args_list,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def controlar_visibilidade_janela_win32(visivel: bool, porta: int = CHROME_PORT) -> bool:
    """
    Modo Fantasma Total no Windows (4 Camadas combinadas):
      - Quando `visivel=False`:
        1) Remove da Barra de Tarefas via COM `ITaskbarList::DeleteTab`
        2) Altera Extended Window Style (`GWL_EXSTYLE`) adicionando `WS_EX_TOOLWINDOW` e removendo `WS_EX_APPWINDOW` (some do Alt+Tab!)
        3) Move janela via `MoveWindow(hwnd, -32000, -32000, 1280, 860, False)`
        4) Oculta completamente o HWND com `ShowWindow(hwnd, SW_HIDE=0)`!
      - Quando `visivel=True`:
        1) Restaura `WS_EX_APPWINDOW` e remove `WS_EX_TOOLWINDOW`
        2) `ShowWindow(hwnd, SW_RESTORE=9)` + `MoveWindow(hwnd, 120, 80, 1280, 860, True)`
        3) Restaura na Barra de Tarefas via `ITaskbarList::AddTab`
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        import psutil

        user32 = ctypes.windll.user32
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        CLSID_TaskbarList = GUID(
            0x56FDF344, 0xFD6D, 0x11D0, (ctypes.c_byte * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90)
        )
        IID_ITaskbarList = GUID(
            0x56FDF342, 0xFD6D, 0x11D0, (ctypes.c_byte * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90)
        )

        p_tbl = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_TaskbarList), None, 1, ctypes.byref(IID_ITaskbarList), ctypes.byref(p_tbl)
        )
        add_tab = None
        del_tab = None
        if hr == 0 and p_tbl.value:
            vtable = ctypes.cast(p_tbl, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])(p_tbl)
            add_tab = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND)(vtable[4])
            del_tab = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND)(vtable[5])

        target_pids = set()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if (proc.info.get("name") or "").lower() == "chrome.exe":
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if f"--remote-debugging-port={porta}" in cmd:
                        target_pids.add(proc.info["pid"])
            except Exception:
                pass

        SW_HIDE = 0
        SW_RESTORE = 9
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000

        def cb(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in target_pids:
                cls_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_name, 256)
                if "Chrome_WidgetWin_1" in cls_name.value:
                    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    if visivel:
                        new_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        user32.MoveWindow(hwnd, 120, 80, 1280, 860, True)
                        if add_tab:
                            add_tab(p_tbl, hwnd)
                        user32.SetForegroundWindow(hwnd)
                    else:
                        if del_tab:
                            del_tab(p_tbl, hwnd)
                        new_style = (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE keeps GPU compositor alive while off-screen
                        user32.MoveWindow(hwnd, -32000, -32000, 1280, 860, False)
                        if del_tab:
                            del_tab(p_tbl, hwnd)
            return 1

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return True
    except Exception:
        return False


async def injetar_bypass_e_silencio(page) -> None:
    js_code = carregar_dom_bypass_js()
    cfg = carregar_config()
    try:
        await page.context.add_init_script(js_code)
    except Exception:
        pass
    try:
        await page.evaluate(js_code)
    except Exception:
        pass

    if cfg.get("mute_audio", True):
        try:
            await page.evaluate("window.__MCP_CREATOR_BYPASS__?.installAudioSilenceShield?.()")
        except Exception:
            pass
        try:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Page.setAudioMuted", {"muted": True})
            await cdp.detach()
        except Exception:
            pass


async def posicionar_janela_chrome(page, invisivel: bool = True, porta: int = CHROME_PORT) -> bool:
    try:
        if not invisivel:
            controlar_visibilidade_janela_win32(visivel=True, porta=porta)

        cdp = await page.context.new_cdp_session(page)
        if carregar_config().get("mute_audio", True):
            try:
                await cdp.send("Page.setAudioMuted", {"muted": True})
            except Exception:
                pass
        win_info = await cdp.send("Browser.getWindowForTarget")
        win_id = win_info["windowId"]
        left_pos = -32000 if invisivel else 120
        top_pos = -32000 if invisivel else 80
        await cdp.send(
            "Browser.setWindowBounds",
            {
                "windowId": win_id,
                "bounds": {
                    "left": left_pos,
                    "top": top_pos,
                    "width": 1280,
                    "height": 860,
                    "windowState": "normal",
                },
            },
        )
        if not invisivel:
            try:
                await cdp.send("Page.bringToFront")
            except Exception:
                pass
        await cdp.detach()

        if invisivel:
            controlar_visibilidade_janela_win32(visivel=False, porta=porta)
        return True
    except Exception:
        controlar_visibilidade_janela_win32(visivel=not invisivel, porta=porta)
        return False


async def obter_parametros_pagina(page) -> dict:
    await injetar_bypass_e_silencio(page)
    try:
        info = await page.evaluate(
            """() => {
                const url = window.location.href || '';
                const host = window.location.hostname || '';
                const path = window.location.pathname || '';
                const isLoginHost = host === 'login.circle.so' || path.includes('/sign_in') || path.includes('/users/sign_in');
                const isOAuthHost = host.includes('accounts.google.com') || host.includes('appleid.apple.com');
                const hasPasswordInput = Boolean(document.querySelector('input[type="password"]'));
                const hasCircleSignals = Boolean(
                    document.querySelector('a[href*="/c/"]') ||
                    document.querySelector('meta[name="csrf-token"]') ||
                    document.querySelector('[data-testid*="sidebar"]') ||
                    document.querySelector('[data-testid*="space"]') ||
                    document.querySelector('.ProseMirror') ||
                    window.circleEnv ||
                    window.__INITIAL_STATE__
                );
                const loggedIn = Boolean(!isLoginHost && !isOAuthHost && !hasPasswordInput && (hasCircleSignals || host.endsWith('.circle.so')));
                const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                return {
                    loggedIn,
                    isLoginHost,
                    isOAuthHost,
                    hasPasswordInput,
                    hasCircleSignals,
                    hasCsrfToken: Boolean(csrf),
                    title: document.title || '',
                    url,
                    origin: window.location.origin,
                };
            }"""
        )
        return info
    except Exception:
        return {"loggedIn": False, "url": page.url if page else "", "origin": ""}


def _resolver_url_circle(page, url_or_slug: str, prefix: str = "/c/") -> str:
    raw = (url_or_slug or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    acc = obter_conta_ativa()
    parsed = urllib.parse.urlparse(page.url if page and page.url else "")
    origin = (
        f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme and parsed.netloc and "login.circle.so" not in parsed.netloc
        else acc.get("community_origin", "https://engenheiros-de-video.circle.so")
    )
    if not raw:
        return origin
    if raw.startswith("/"):
        return f"{origin}{raw}"
    return f"{origin}{prefix}{raw}"


def _extrair_texto_tiptap(tiptap_obj: Any) -> str:
    """Extrai texto limpo e legível da árvore `tiptap_body` / `rich_text_body` do Circle.so."""
    if not tiptap_obj:
        return ""
    if isinstance(tiptap_obj, str):
        return tiptap_obj.strip()
    if isinstance(tiptap_obj, dict):
        if tiptap_obj.get("circle_ios_fallback_text"):
            return str(tiptap_obj["circle_ios_fallback_text"]).strip()
        body_node = tiptap_obj.get("body")
        if isinstance(body_node, dict):
            parts: List[str] = []

            def _walk(node: Any):
                if isinstance(node, dict):
                    if node.get("type") == "text" and node.get("text"):
                        parts.append(str(node["text"]))
                    elif node.get("type") in ("hardBreak", "paragraph"):
                        if parts and not parts[-1].endswith("\n"):
                            parts.append("\n")
                    for child in node.get("content") or []:
                        _walk(child)
                elif isinstance(node, list):
                    for item in node:
                        _walk(item)

            _walk(body_node)
            return "".join(parts).strip()
    return ""


# ============================================================================
# 1. COMUNIDADES & SPACES (`circle_list_spaces`)
# ============================================================================


async def listar_spaces_e_chats(page, community_url: str = "") -> Dict[str, Any]:
    """
    Lista a comunidade atual (`/internal_api/communities`), todos os Spaces (`/internal_api/spaces?per_page=50`),
    todas as salas de chat/DMs (`/internal_api/chat_rooms`) e threads de chat (`/internal_api/chat_threads`).
    """
    if community_url and community_url.startswith("http"):
        await page.goto(community_url, wait_until="domcontentloaded")
        await asyncio.sleep(2.0)

    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "current_url": page.url}

    data = await page.evaluate(
        """async () => {
            const origin = window.location.origin;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            const [community, spacesResp, chatRoomsResp, chatThreadsResp] = await Promise.all([
                getJ('/internal_api/communities'),
                getJ('/internal_api/spaces?per_page=50'),
                getJ('/internal_api/chat_rooms'),
                getJ('/internal_api/chat_threads'),
            ]);

            const spaces = ((spacesResp && spacesResp.records) || []).map(s => ({
                id: s.id,
                name: s.name,
                slug: s.slug,
                post_type: s.post_type || 'posts',
                display_view: s.display_view,
                space_group_name: s.space_group_name,
                chat_room_id: s.chat_room_id,
                space_members_count: s.space_members_count,
                url: `${origin}/c/${s.slug}`,
            }));

            const direct_and_group_chats = ((chatRoomsResp && chatRoomsResp.records) || []).map(c => ({
                id: c.id,
                uuid: c.uuid,
                name: c.chat_room_name,
                kind: c.chat_room_kind,
                unread_count: c.unread_messages_count || 0,
                last_message: c.last_message ? {
                    id: c.last_message.id,
                    body: c.last_message.body,
                    created_at: c.last_message.created_at,
                } : null,
            }));

            // Descobre UUIDs de salas de chat de comunidade via chat_threads
            const discovered_chat_uuids = {};
            for (const th of ((chatThreadsResp && chatThreadsResp.records) || [])) {
                const pm = th.parent_message;
                if (pm && pm.chat_room_id && pm.chat_room_uuid) {
                    discovered_chat_uuids[pm.chat_room_id] = pm.chat_room_uuid;
                }
            }

            for (const sp of spaces) {
                if (sp.chat_room_id && discovered_chat_uuids[sp.chat_room_id]) {
                    sp.chat_room_uuid = discovered_chat_uuids[sp.chat_room_id];
                }
            }

            return {
                community: community ? {
                    id: community.id,
                    name: community.name,
                    slug: community.slug,
                    public_uid: community.public_uid,
                    origin,
                } : { origin, title: document.title },
                spaces_count: spaces.length,
                spaces,
                direct_and_group_chats_count: direct_and_group_chats.length,
                direct_and_group_chats,
                discovered_chat_uuids,
            };
        }"""
    )

    return {"ok": True, "logged_in": True, **data}


# ============================================================================
# 2. CHAT AO VIVO & DMs (`circle_get_chat_messages` & `circle_send_chat_message`)
# ============================================================================


async def obter_mensagens_chat(page, chat_url_or_slug: str = "papo", limit: int = 40) -> Dict[str, Any]:
    """
    Puxa as mensagens recentes do Chat da comunidade (ex: 'papo' -> uuid 9deb17c9-e35a-448e-8322-164241947ef8)
    ou de qualquer DM (`uuid` de `/internal_api/chat_rooms`) diretamente via `/internal_api/chat_rooms/<uuid>/messages`!
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    raw_res = await page.evaluate(
        """async (args) => {
            const [targetSlugOrUuid, maxItems, defaultPapoUuid] = args;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            let chatUuid = '';
            const cleanTarget = (targetSlugOrUuid || 'papo').trim().replace(/^\\/c\\//, '').replace(/\\/$/, '');

            // Se já parece um UUID (contém hífens hexadecimais)
            if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(cleanTarget)) {
                chatUuid = cleanTarget;
            } else if (cleanTarget.toLowerCase() === 'papo' || cleanTarget === '') {
                chatUuid = defaultPapoUuid;
            } else {
                // Procura pelo nome ou identifier em /internal_api/chat_rooms
                const rooms = await getJ('/internal_api/chat_rooms');
                for (const r of ((rooms && rooms.records) || [])) {
                    if (
                        (r.chat_room_name || '').toLowerCase().includes(cleanTarget.toLowerCase()) ||
                        String(r.id) === cleanTarget ||
                        r.uuid === cleanTarget
                    ) {
                        chatUuid = r.uuid;
                        break;
                    }
                }
            }

            if (!chatUuid) {
                chatUuid = defaultPapoUuid;
            }

            const msgResp = await getJ(`/internal_api/chat_rooms/${chatUuid}/messages`);
            const records = (msgResp && msgResp.records) || [];
            return {
                chat_room_uuid: chatUuid,
                total_count: msgResp ? msgResp.total_count : records.length,
                records: records.slice(-maxItems),
            };
        }""",
        [chat_url_or_slug or "papo", int(limit), DEFAULT_PAPO_CHAT_UUID],
    )

    messages = []
    for m in raw_res.get("records") or []:
        rt = m.get("rich_text_body") or {}
        sender = m.get("sender") or m.get("user") or m.get("chat_room_participant") or {}
        text = m.get("body") or _extrair_texto_tiptap(rt)
        messages.append(
            {
                "id": m.get("id"),
                "created_at": m.get("created_at") or m.get("sent_at"),
                "chat_room_id": m.get("chat_room_id"),
                "chat_room_uuid": m.get("chat_room_uuid"),
                "participant_id": m.get("chat_room_participant_id"),
                "author_name": sender.get("name") if isinstance(sender, dict) else "",
                "text": text,
                "replies_count": m.get("replies_count", 0),
                "reactions": m.get("reactions", []),
                "attachments": rt.get("attachments", []) if isinstance(rt, dict) else [],
            }
        )

    return {
        "ok": True,
        "logged_in": True,
        "chat_room_uuid": raw_res.get("chat_room_uuid"),
        "total_messages_in_room": raw_res.get("total_count"),
        "returned_count": len(messages),
        "messages": messages,
    }


async def enviar_mensagem_chat(
    page,
    message: str,
    chat_url_or_slug: str = "papo",
    attachment_path: str = "",
) -> Dict[str, Any]:
    """
    Envia uma mensagem no Chat Space (ex: 'papo') ou DM:
      - Camada 1: POST direto em `/internal_api/chat_rooms/<uuid>/messages` com payload TipTap + CSRF token (se sem anexo).
      - Camada 2 (Fallback ou com anexo): Navega para `/c/<slug>`, preenche o editor ProseMirror e envia!
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    if not attachment_path:
        api_send = await page.evaluate(
            """async (args) => {
                const [targetSlugOrUuid, msgText, defaultPapoUuid] = args;
                const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                const headers = {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                };
                if (csrf) headers['X-CSRF-Token'] = csrf;

                let chatUuid = defaultPapoUuid;
                const cleanTarget = (targetSlugOrUuid || 'papo').trim().replace(/^\\/c\\//, '').replace(/\\/$/, '');
                if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(cleanTarget)) {
                    chatUuid = cleanTarget;
                } else if (cleanTarget.toLowerCase() !== 'papo' && cleanTarget !== '') {
                    try {
                        const r = await fetch('/internal_api/chat_rooms', { credentials: 'include', headers });
                        if (r.ok) {
                            const rooms = await r.json();
                            for (const rm of (rooms.records || [])) {
                                if ((rm.chat_room_name || '').toLowerCase().includes(cleanTarget.toLowerCase())) {
                                    chatUuid = rm.uuid;
                                    break;
                                }
                            }
                        }
                    } catch (e) {}
                }

                const payload = {
                    chat_room_message: {
                        body: msgText,
                        rich_text_body: {
                            body: {
                                type: 'doc',
                                content: [
                                    {
                                        type: 'paragraph',
                                        content: [{ type: 'text', text: msgText }]
                                    }
                                ]
                            },
                            circle_ios_fallback_text: msgText,
                            attachments: []
                        }
                    }
                };

                try {
                    const resp = await fetch(`/internal_api/chat_rooms/${chatUuid}/messages`, {
                        method: 'POST',
                        credentials: 'include',
                        headers,
                        body: JSON.stringify(payload),
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        return { ok: true, method: 'internal_api_post', chat_room_uuid: chatUuid, response: data };
                    }
                    return { ok: false, status: resp.status };
                } catch (e) {
                    return { ok: false, error: String(e) };
                }
            }""",
            [chat_url_or_slug or "papo", message, DEFAULT_PAPO_CHAT_UUID],
        )
        if isinstance(api_send, dict) and api_send.get("ok"):
            return {
                "ok": True,
                "action": "send_chat_message",
                "sent_method": "internal_api_post",
                "chat_room_uuid": api_send.get("chat_room_uuid"),
                "message_sent": message,
                "message_id": (api_send.get("response") or {}).get("id"),
            }

    # Fallback DOM ProseMirror
    target = _resolver_url_circle(page, chat_url_or_slug or "papo", prefix="/c/")
    if page.url != target:
        await page.goto(target, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

    sels = carregar_seletores().get("selectors", {})
    if attachment_path and os.path.exists(attachment_path):
        file_inp = page.locator(sels.get("file_input", 'input[type="file"]')).first
        if await file_inp.count() > 0:
            await file_inp.set_input_files(attachment_path)
            await asyncio.sleep(1.5)

    sel_chat_input = sels.get(
        "chat_input_editor",
        '.ProseMirror[contenteditable="true"], [role="textbox"][contenteditable="true"], textarea',
    )
    editor = page.locator(sel_chat_input).last
    if await editor.count() == 0:
        raise RuntimeError(f"Campo de chat não encontrado em {page.url}")

    await editor.click()
    await asyncio.sleep(0.2)
    await page.keyboard.insert_text(message)
    await asyncio.sleep(0.4)
    await page.keyboard.press("Enter")
    await asyncio.sleep(1.2)
    return {
        "ok": True,
        "action": "send_chat_message",
        "sent_method": "dom_prosemirror",
        "chat_url": page.url,
        "message_sent": message,
    }


# ============================================================================
# 3. FEED, POSTAGENS, COMENTÁRIOS & LIKES (`circle_get_posts`, `circle_get_post_comments`, `circle_create_post`, `circle_comment_post`, `circle_like_post`)
# ============================================================================


async def obter_posts_space(page, space_url_or_slug: str = "", limit: int = 15) -> Dict[str, Any]:
    """
    Puxa os posts recentes de qualquer Space (ex: 'edicao', 'ia', 'motion', 'negocios', 'get-brolls', 'projetos')
    ou do Feed geral (`space_url_or_slug=""` ou `"feed"`) via `/internal_api/spaces/<id>/posts` ou `/internal_api/home_page_posts`.
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    raw_posts = await page.evaluate(
        """async (args) => {
            const [targetSpace, maxPosts] = args;
            const origin = window.location.origin;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            let clean = (targetSpace || '').trim();
            if (clean.startsWith('http')) {
                const m = clean.match(/\\/c\\/([^/?#]+)/);
                clean = m ? m[1] : '';
            } else {
                clean = clean.replace(/^\\/c\\//, '').replace(/\\/$/, '');
            }

            let spaceInfo = null;
            let postsResp = null;

            if (!clean || clean === 'feed' || clean === 'home') {
                postsResp = await getJ('/internal_api/home_page_posts?sort=latest&page=1');
            } else {
                const spacesResp = await getJ('/internal_api/spaces?per_page=50');
                const spaces = (spacesResp && spacesResp.records) || [];
                spaceInfo = spaces.find(s =>
                    s.slug === clean ||
                    String(s.id) === clean ||
                    (s.name || '').toLowerCase() === clean.toLowerCase()
                );
                if (spaceInfo) {
                    postsResp = await getJ(`/internal_api/spaces/${spaceInfo.id}/posts?page=1`);
                } else {
                    postsResp = await getJ('/internal_api/home_page_posts?sort=latest&page=1');
                }
            }

            const records = ((postsResp && postsResp.records) || []).slice(0, maxPosts);
            return {
                origin,
                space: spaceInfo ? { id: spaceInfo.id, name: spaceInfo.name, slug: spaceInfo.slug } : { slug: 'feed', name: 'Feed Geral' },
                total_in_space: (postsResp && postsResp.count) || records.length,
                records,
            };
        }""",
        [space_url_or_slug or "", int(limit)],
    )

    origin = raw_posts.get("origin", "https://engenheiros-de-video.circle.so")
    space_slug = (raw_posts.get("space") or {}).get("slug", "feed")
    posts = []
    for p in raw_posts.get("records") or []:
        author = p.get("author") or p.get("user") or p.get("community_member") or {}
        body_txt = _extrair_texto_tiptap(p.get("tiptap_body")) or (p.get("body_trix_content") or "")
        p_slug = p.get("slug") or ""
        p_space_slug = (p.get("space") or {}).get("slug") or space_slug
        posts.append(
            {
                "id": p.get("id"),
                "title": p.get("name") or p.get("display_title") or "",
                "slug": p_slug,
                "url": f"{origin}/c/{p_space_slug}/{p_slug}" if p_slug and p_space_slug != "feed" else f"{origin}/c/{p_slug}",
                "published_at": p.get("published_at") or p.get("created_at"),
                "user_id": p.get("user_id"),
                "community_member_id": p.get("community_member_id"),
                "author_name": author.get("name") if isinstance(author, dict) else "",
                "comments_count": p.get("comments_count", 0),
                "likes_count": p.get("user_likes_count", p.get("likes_count", 0)),
                "body": body_txt[:3500],
            }
        )

    return {
        "ok": True,
        "logged_in": True,
        "space": raw_posts.get("space"),
        "total_in_space": raw_posts.get("total_in_space"),
        "returned_count": len(posts),
        "posts": posts,
    }


async def obter_comentarios_post(page, post_id_or_url: str, page_num: int = 1) -> Dict[str, Any]:
    """
    Puxa todos os comentários de um post via `/internal_api/posts/<post_id>/comments?page=<page_num>`.
    Aceita o ID numérico do post (ex: '38565655') ou a URL do post.
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    raw_comments = await page.evaluate(
        """async (args) => {
            const [postIdOrUrl, pg] = args;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            let postId = String(postIdOrUrl || '').trim();
            if (!/^\\d+$/.test(postId)) {
                // Procura o post pelo slug no feed recente
                const feed = await getJ('/internal_api/home_page_posts?sort=latest&page=1');
                for (const p of ((feed && feed.records) || [])) {
                    if (postId.includes(p.slug) || p.slug === postId) {
                        postId = String(p.id);
                        break;
                    }
                }
            }

            const resp = await getJ(`/internal_api/posts/${postId}/comments?page=${pg}`);
            return {
                post_id: postId,
                count: resp ? resp.count : 0,
                records: (resp && resp.records) || [],
            };
        }""",
        [str(post_id_or_url), int(page_num)],
    )

    comments = []
    for c in raw_comments.get("records") or []:
        author = c.get("author") or c.get("user") or c.get("community_member") or {}
        body_txt = _extrair_texto_tiptap(c.get("tiptap_body")) or c.get("body_text") or c.get("body") or ""
        comments.append(
            {
                "id": c.get("id"),
                "post_id": c.get("post_id"),
                "parent_comment_id": c.get("parent_comment_id"),
                "created_at": c.get("created_at"),
                "author_name": author.get("name") if isinstance(author, dict) else "",
                "user_id": c.get("user_id"),
                "likes_count": c.get("user_likes_count", 0),
                "text": body_txt,
            }
        )

    return {
        "ok": True,
        "post_id": raw_comments.get("post_id"),
        "total_comments": raw_comments.get("count"),
        "comments": comments,
    }


async def _upload_attachment_active_storage(page, attachment_path: str) -> Optional[Dict[str, Any]]:
    """
    Faz upload nativo de imagem/arquivo via Rails ActiveStorage (`/rails/active_storage/direct_uploads`)
    dentro da sessão autenticada do Circle.so em 100% Modo Fantasma, retornando `signed_id` e `blob_id`
    para embutir imagens diretamente no `tiptap_body`!
    """
    if not attachment_path or not os.path.exists(attachment_path):
        return None
    p = Path(attachment_path)
    raw_bytes = p.read_bytes()
    md5_b64 = base64.b64encode(hashlib.md5(raw_bytes).digest()).decode("ascii")
    b64_data = base64.b64encode(raw_bytes).decode("ascii")
    mime_type = mimetypes.guess_type(str(p))[0] or "image/jpeg"

    res = await page.evaluate(
        """async (args) => {
            const [filename, byteSize, checksum, contentType, b64Data] = args;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            for (const ep of ['/rails/active_storage/direct_uploads', '/internal_api/direct_uploads']) {
                try {
                    const r = await fetch(ep, {
                        method: 'POST',
                        credentials: 'include',
                        headers,
                        body: JSON.stringify({
                            blob: {
                                filename,
                                byte_size: byteSize,
                                checksum,
                                content_type: contentType
                            }
                        })
                    });
                    if (r.ok) {
                        const j = await r.json();
                        const binStr = atob(b64Data);
                        const arr = new Uint8Array(binStr.length);
                        for (let i = 0; i < binStr.length; i++) arr[i] = binStr.charCodeAt(i);
                        const putRes = await fetch(j.direct_upload.url, {
                            method: 'PUT',
                            headers: j.direct_upload.headers,
                            body: arr.buffer
                        });
                        if (putRes.ok) {
                            return {
                                ok: true,
                                signed_id: j.signed_id,
                                blob_id: j.id,
                                filename,
                                content_type: contentType
                            };
                        }
                    }
                } catch (e) {}
            }
            return { ok: false };
        }""",
        [p.name, len(raw_bytes), md5_b64, mime_type, b64_data],
    )
    return res if isinstance(res, dict) and res.get("ok") else None


async def criar_post_space(
    page,
    space_url_or_slug: str,
    title: str,
    body: str,
    attachment_path: str = "",
) -> Dict[str, Any]:
    """
    Cria e publica uma nova postagem em um Space da comunidade do Circle.so:
      - Camada 1: Faz upload da imagem/anexo via ActiveStorage DirectUpload (`signed_id`) se `attachment_path`
        for informado e dispara `POST /internal_api/spaces/<space_id>/posts` com payload TipTap + CSRF token.
      - Camada 2 (Fallback): Automação via interface ProseMirror do Circle.
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    uploaded_blob = None
    if attachment_path and os.path.exists(attachment_path):
        uploaded_blob = await _upload_attachment_active_storage(page, attachment_path)

    signed_id = (uploaded_blob or {}).get("signed_id", "")

    api_create = await page.evaluate(
        """async (args) => {
            const [targetSpace, postTitle, postBody, imgSignedId] = args;
            const origin = window.location.origin;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            let clean = (targetSpace || '').trim().replace(/^\\/c\\//, '').replace(/\\/$/, '');
            const spacesResp = await (await fetch('/internal_api/spaces?per_page=50', { credentials: 'include', headers })).json();
            const spaceInfo = (spacesResp.records || []).find(s =>
                s.slug === clean ||
                String(s.id) === clean ||
                (s.name || '').toLowerCase() === clean.toLowerCase()
            );
            if (!spaceInfo) return { ok: false, reason: 'space_not_found' };

            const contentNodes = [];
            if (imgSignedId) {
                contentNodes.push({
                    type: 'image',
                    attrs: {
                        url: null,
                        href: null,
                        width: null,
                        alignment: 'center',
                        signed_id: imgSignedId,
                        width_ratio: null,
                        content_type: null,
                        use_intrinsic_size: false
                    }
                });
            }

            function buildParagraphNodes(lineText) {
                // Converte URLs (https://...) e menções @[Nome](url) em nós de texto com link clicável nativo do TipTap
                const regex = /(@\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)]+)/g;
                const parts = lineText.split(regex).filter(Boolean);
                const inlineNodes = [];
                for (const part of parts) {
                    const mentionMatch = part.match(/^@\[([^\]]+)\]\(([^)]+)\)$/);
                    if (mentionMatch) {
                        const label = '@' + mentionMatch[1];
                        const href = mentionMatch[2];
                        inlineNodes.push({
                            type: 'text',
                            text: label,
                            circle_ios_fallback_text: label,
                            marks: [
                                { type: 'bold' },
                                {
                                    type: 'link',
                                    attrs: {
                                        href,
                                        target: '_blank',
                                        rel: 'noopener noreferrer nofollow',
                                        class: null,
                                        title: null
                                    }
                                }
                            ]
                        });
                    } else if (/^https?:\/\//.test(part)) {
                        inlineNodes.push({
                            type: 'text',
                            text: part,
                            circle_ios_fallback_text: part,
                            marks: [
                                {
                                    type: 'link',
                                    attrs: {
                                        href: part,
                                        target: '_blank',
                                        rel: 'noopener noreferrer nofollow',
                                        class: null,
                                        title: null
                                    }
                                }
                            ]
                        });
                    } else {
                        inlineNodes.push({
                            type: 'text',
                            text: part,
                            circle_ios_fallback_text: part
                        });
                    }
                }
                return {
                    type: 'paragraph',
                    content: inlineNodes.length ? inlineNodes : [{ type: 'text', text: lineText, circle_ios_fallback_text: lineText }]
                };
            }

            const blockParts = postBody.split(/(```[\\s\\S]*?```)/g).filter(Boolean);
            for (const bp of blockParts) {
                if (bp.startsWith('```') && bp.endsWith('```')) {
                    const inner = bp.replace(/^```[a-zA-Z0-9_-]*\\n?/, '').replace(/\\n?```$/, '').trim();
                    if (inner) {
                        contentNodes.push({
                            type: 'codeBlock',
                            attrs: { language: null },
                            content: [{ type: 'text', text: inner, circle_ios_fallback_text: inner }]
                        });
                    }
                } else {
                    const paragraphs = bp.split(/\\n+/).map(s => s.trim()).filter(Boolean).map(p => buildParagraphNodes(p));
                    contentNodes.push(...paragraphs);
                }
            }

            const payload = {
                post: {
                    name: postTitle,
                    space_id: spaceInfo.id,
                    is_comments_enabled: true,
                    is_liking_enabled: true,
                    tiptap_body: {
                        body: {
                            type: 'doc',
                            content: contentNodes
                        }
                    }
                }
            };

            try {
                // Se já existe um post recente com o mesmo título neste Space, atualiza in-place via PUT para não duplicar!
                let existingPostId = null;
                try {
                    const recentResp = await (await fetch(`/internal_api/spaces/${spaceInfo.id}/posts?page=1`, { credentials: 'include', headers })).json();
                    const found = (recentResp.records || []).find(p => (p.name || '').trim() === postTitle.trim());
                    if (found) existingPostId = found.id;
                } catch (e) {}

                const method = existingPostId ? 'PUT' : 'POST';
                const endpointUrl = existingPostId
                    ? `/internal_api/spaces/${spaceInfo.id}/posts/${existingPostId}`
                    : `/internal_api/spaces/${spaceInfo.id}/posts`;

                const resp = await fetch(endpointUrl, {
                    method,
                    credentials: 'include',
                    headers,
                    body: JSON.stringify(payload),
                });
                if (resp.ok) {
                    const created = await resp.json();
                    return { ok: true, method: existingPostId ? 'internal_api_put_updated' : 'internal_api_post', origin, space: spaceInfo, created };
                }
                const errTxt = await resp.text();
                return { ok: false, status: resp.status, error_body: errTxt.slice(0, 500) };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        }""",
        [space_url_or_slug, title, body, signed_id],
    )
    if isinstance(api_create, dict) and api_create.get("ok"):
        created = api_create.get("created") or {}
        sp = api_create.get("space") or {}
        origin = api_create.get("origin", "https://engenheiros-de-video.circle.so")
        post_slug = created.get("slug") or ""
        sp_slug = sp.get("slug") or space_url_or_slug
        post_url = f"{origin}/c/{sp_slug}/{post_slug}" if post_slug else f"{origin}/c/{sp_slug}"
        return {
            "ok": True,
            "action": "edit_post" if api_create.get("method") == "internal_api_put_updated" else "create_post",
            "method": api_create.get("method"),
            "post_id": created.get("id"),
            "slug": post_slug,
            "space_id": sp.get("id"),
            "space_slug": sp_slug,
            "post_url": post_url,
            "image_signed_id": signed_id,
            "title": title,
        }


async def editar_post_space(
    page,
    space_url_or_slug: str,
    post_id_or_slug: str,
    title: str = "",
    body: str = "",
    attachment_path: str = "",
    keep_existing_image_signed_id: str = "",
) -> Dict[str, Any]:
    """
    Edita uma postagem existente in-place via `PUT /internal_api/spaces/<space_id>/posts/<post_id>`
    sem criar post duplicado! Preserva a imagem de capa (`keep_existing_image_signed_id` ou faz novo upload
    se `attachment_path` for passado) e converte URLs `https://...` e menções `@[Nome](url)` em links clicáveis do TipTap.
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    uploaded_blob = None
    if attachment_path and os.path.exists(attachment_path):
        uploaded_blob = await _upload_attachment_active_storage(page, attachment_path)

    signed_id = (uploaded_blob or {}).get("signed_id") or keep_existing_image_signed_id

    api_edit = await page.evaluate(
        """async (args) => {
            const [targetSpace, postIdOrSlug, newTitle, newBody, imgSignedId] = args;
            const origin = window.location.origin;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            let cleanSpace = (targetSpace || '').trim().replace(/^\\/c\\//, '').replace(/\\/$/, '');
            const spacesResp = await (await fetch('/internal_api/spaces?per_page=50', { credentials: 'include', headers })).json();
            const spaceInfo = (spacesResp.records || []).find(s =>
                s.slug === cleanSpace ||
                String(s.id) === cleanSpace ||
                (s.name || '').toLowerCase() === cleanSpace.toLowerCase()
            );
            if (!spaceInfo) return { ok: false, reason: 'space_not_found' };

            const postsResp = await (await fetch(`/internal_api/spaces/${spaceInfo.id}/posts?page=1`, { credentials: 'include', headers })).json();
            const targetClean = String(postIdOrSlug || '').trim();
            const existingPost = (postsResp.records || []).find(p =>
                String(p.id) === targetClean ||
                p.slug === targetClean ||
                targetClean.includes(p.slug)
            );
            const postId = existingPost ? existingPost.id : targetClean;
            const finalTitle = newTitle || (existingPost ? existingPost.name : '');

            // Preserva signed_id da imagem anterior caso nenhuma nova tenha sido enviada
            let finalSignedId = imgSignedId;
            if (!finalSignedId && existingPost && existingPost.tiptap_body && existingPost.tiptap_body.body) {
                for (const node of (existingPost.tiptap_body.body.content || [])) {
                    if (node.type === 'image' && node.attrs && node.attrs.signed_id) {
                        finalSignedId = node.attrs.signed_id;
                        break;
                    }
                }
            }

            function buildParagraphNodes(lineText) {
                const regex = /(@\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)]+)/g;
                const parts = lineText.split(regex).filter(Boolean);
                const inlineNodes = [];
                for (const part of parts) {
                    const mentionMatch = part.match(/^@\[([^\]]+)\]\(([^)]+)\)$/);
                    if (mentionMatch) {
                        const label = '@' + mentionMatch[1];
                        const href = mentionMatch[2];
                        inlineNodes.push({
                            type: 'text',
                            text: label,
                            circle_ios_fallback_text: label,
                            marks: [
                                { type: 'bold' },
                                {
                                    type: 'link',
                                    attrs: {
                                        href,
                                        target: '_blank',
                                        rel: 'noopener noreferrer nofollow',
                                        class: null,
                                        title: null
                                    }
                                }
                            ]
                        });
                    } else if (/^https?:\/\//.test(part)) {
                        inlineNodes.push({
                            type: 'text',
                            text: part,
                            circle_ios_fallback_text: part,
                            marks: [
                                {
                                    type: 'link',
                                    attrs: {
                                        href: part,
                                        target: '_blank',
                                        rel: 'noopener noreferrer nofollow',
                                        class: null,
                                        title: null
                                    }
                                }
                            ]
                        });
                    } else {
                        inlineNodes.push({
                            type: 'text',
                            text: part,
                            circle_ios_fallback_text: part
                        });
                    }
                }
                return {
                    type: 'paragraph',
                    content: inlineNodes.length ? inlineNodes : [{ type: 'text', text: lineText, circle_ios_fallback_text: lineText }]
                };
            }

            const contentNodes = [];
            if (finalSignedId) {
                contentNodes.push({
                    type: 'image',
                    attrs: {
                        url: null,
                        href: null,
                        width: null,
                        alignment: 'center',
                        signed_id: finalSignedId,
                        width_ratio: null,
                        content_type: null,
                        use_intrinsic_size: false
                    }
                });
            }

            const paragraphs = newBody.split(/\\n+/).filter(Boolean).map(p => buildParagraphNodes(p));
            contentNodes.push(...paragraphs);

            const payload = {
                post: {
                    name: finalTitle,
                    space_id: spaceInfo.id,
                    is_comments_enabled: true,
                    is_liking_enabled: true,
                    tiptap_body: {
                        body: {
                            type: 'doc',
                            content: contentNodes
                        }
                    }
                }
            };

            const postSlug = existingPost ? existingPost.slug : targetClean;
            const candidateUrls = [
                `/internal_api/spaces/${spaceInfo.id}/posts/${postSlug}`,
                `/internal_api/spaces/${spaceInfo.slug}/posts/${postSlug}`,
                `/internal_api/posts/${postId}`,
                `/internal_api/spaces/${spaceInfo.id}/posts/${postId}`,
            ];

            let lastStatus = 0;
            let lastErr = '';
            for (const epUrl of candidateUrls) {
                for (const mth of ['PUT', 'PATCH']) {
                    try {
                        const resp = await fetch(epUrl, {
                            method: mth,
                            credentials: 'include',
                            headers,
                            body: JSON.stringify(payload),
                        });
                        lastStatus = resp.status;
                        if (resp.ok) {
                            const updated = await resp.json();
                            return { ok: true, method: `${mth} ${epUrl}`, origin, space: spaceInfo, updated, finalSignedId };
                        }
                        lastErr = (await resp.text()).slice(0, 300);
                    } catch (e) {
                        lastErr = String(e);
                    }
                }
            }
            return { ok: false, status: lastStatus, error_body: lastErr, post_id: postId, post_slug: postSlug, space_slug: spaceInfo.slug };
        }""",
        [space_url_or_slug, str(post_id_or_slug), title, body, signed_id],
    )
    if isinstance(api_edit, dict) and api_edit.get("ok"):
        updated = api_edit.get("updated") or {}
        sp = api_edit.get("space") or {}
        origin = api_edit.get("origin", "https://engenheiros-de-video.circle.so")
        post_slug = updated.get("slug") or ""
        sp_slug = sp.get("slug") or space_url_or_slug
        return {
            "ok": True,
            "action": "edit_post",
            "method": "internal_api_put",
            "post_id": updated.get("id"),
            "slug": post_slug,
            "space_id": sp.get("id"),
            "space_slug": sp_slug,
            "post_url": f"{origin}/c/{sp_slug}/{post_slug}" if post_slug else f"{origin}/c/{sp_slug}",
            "image_signed_id": api_edit.get("finalSignedId"),
            "title": updated.get("name") or title,
        }
    return {"ok": False, "details": api_edit}

    # Camada 2: Fallback DOM ProseMirror
    target = _resolver_url_circle(page, space_url_or_slug, prefix="/c/")
    if page.url != target:
        await page.goto(target, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

    sels = carregar_seletores().get("selectors", {})
    sel_trigger = sels.get(
        "new_post_trigger",
        '[data-testid*="new-post"], button:has-text("New post"), button:has-text("Novo post"), button:has-text("Start a post"), [placeholder*="Start a post"]',
    )
    trigger = page.locator(sel_trigger).first
    if await trigger.count() > 0:
        await trigger.click()
        await asyncio.sleep(1.5)

    if title:
        sel_title = sels.get(
            "post_title_input",
            '[data-testid*="post-title"], input[placeholder*="Title"], textarea[placeholder*="Title"], input[placeholder*="Título"], textarea[placeholder*="Título"]',
        )
        title_loc = page.locator(sel_title).first
        if await title_loc.count() > 0:
            await title_loc.click()
            await title_loc.fill(title)
            await asyncio.sleep(0.3)

    sel_body = sels.get(
        "post_body_editor",
        '.ProseMirror[contenteditable="true"], [role="textbox"][contenteditable="true"], textarea',
    )
    body_loc = page.locator(sel_body).last
    if await body_loc.count() == 0:
        raise RuntimeError(f"Editor de corpo do post não encontrado em {page.url}")

    await body_loc.click()
    await asyncio.sleep(0.2)
    await page.keyboard.insert_text(body)
    await asyncio.sleep(0.5)

    if attachment_path and os.path.exists(attachment_path):
        file_inp = page.locator(sels.get("file_input", 'input[type="file"]')).first
        if await file_inp.count() > 0:
            await file_inp.set_input_files(attachment_path)
            await asyncio.sleep(2.0)

    sel_pub = sels.get(
        "post_publish_btn",
        '[data-testid*="publish"], [data-testid*="submit-post"], button:has-text("Publish"), button:has-text("Publicar"), button:has-text("Post")',
    )
    pub_btn = page.locator(sel_pub).last
    await pub_btn.click()
    await asyncio.sleep(2.5)

    return {
        "ok": True,
        "action": "create_post",
        "method": "dom_prosemirror",
        "space_url": page.url,
        "title": title,
    }


async def comentar_post(page, post_url: str, comment_text: str) -> Dict[str, Any]:
    """Comenta em um post via `/internal_api/posts/<post_id>/comments` ou fallback DOM ProseMirror."""
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    if str(post_url).strip().isdigit():
        api_comment = await page.evaluate(
            """async (args) => {
                const [postId, txt] = args;
                const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                const headers = {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                };
                if (csrf) headers['X-CSRF-Token'] = csrf;
                const payload = {
                    comment: {
                        body: txt,
                        tiptap_body: {
                            body: {
                                type: 'doc',
                                content: [{ type: 'paragraph', content: [{ type: 'text', text: txt }] }]
                            }
                        }
                    }
                };
                try {
                    const r = await fetch(`/internal_api/posts/${postId}/comments`, {
                        method: 'POST',
                        credentials: 'include',
                        headers,
                        body: JSON.stringify(payload),
                    });
                    if (r.ok) return { ok: true, data: await r.json() };
                    return { ok: false, status: r.status };
                } catch (e) {
                    return { ok: false, error: String(e) };
                }
            }""",
            [str(post_url).strip(), comment_text],
        )
        if isinstance(api_comment, dict) and api_comment.get("ok"):
            return {
                "ok": True,
                "action": "comment_post",
                "method": "internal_api_post",
                "post_id": str(post_url).strip(),
                "comment_sent": comment_text,
            }

    target = _resolver_url_circle(page, post_url, prefix="/c/")
    if page.url != target:
        await page.goto(target, wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

    sels = carregar_seletores().get("selectors", {})
    sel_comment = sels.get(
        "comment_editor",
        '.ProseMirror[contenteditable="true"], [placeholder*="comment"], [placeholder*="comentário"], textarea',
    )
    editor = page.locator(sel_comment).last
    await editor.click()
    await asyncio.sleep(0.2)
    await page.keyboard.insert_text(comment_text)
    await asyncio.sleep(0.4)

    sel_submit = sels.get(
        "comment_submit_btn",
        'button:has-text("Post comment"), button:has-text("Comment"), button:has-text("Comentar"), button:has-text("Reply"), button:has-text("Enviar")',
    )
    btn = page.locator(sel_submit).last
    if await btn.count() > 0:
        await btn.click()
    else:
        await page.keyboard.press("Control+Enter")

    await asyncio.sleep(1.8)
    return {
        "ok": True,
        "action": "comment_post",
        "method": "dom_prosemirror",
        "post_url": page.url,
        "comment_sent": comment_text,
    }


async def curtir_post(page, post_id_or_url: str) -> Dict[str, Any]:
    """Dá like em um post da comunidade via `POST /internal_api/posts/<post_id>/user_likes`."""
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    res = await page.evaluate(
        """async (postIdOrUrl) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            let postId = String(postIdOrUrl || '').trim();
            if (!/^\\d+$/.test(postId)) {
                const feed = await (await fetch('/internal_api/home_page_posts?sort=latest&page=1', { credentials: 'include', headers })).json();
                for (const p of (feed.records || [])) {
                    if (postId.includes(p.slug) || p.slug === postId) {
                        postId = String(p.id);
                        break;
                    }
                }
            }

            try {
                const r = await fetch(`/internal_api/posts/${postId}/user_likes`, {
                    method: 'POST',
                    credentials: 'include',
                    headers,
                });
                return { ok: r.ok, status: r.status, post_id: postId };
            } catch (e) {
                return { ok: false, error: String(e), post_id: postId };
            }
        }""",
        str(post_id_or_url),
    )
    return {"action": "like_post", **res}


# ============================================================================
# 4. BUSCA GLOBAL & RADAR DE OPORTUNIDADES / VAGAS (`circle_search`)
# ============================================================================


async def buscar_na_comunidade(
    page,
    query: str,
    include_chat: bool = True,
    limit: int = 25,
) -> Dict[str, Any]:
    """
    Radar de Busca Global na comunidade Circle:
    Vasculha simultaneamente o Feed de Posts (`/internal_api/home_page_posts`), o Space de Oportunidades
    (`/c/motion` id 2919735), Edição (`/c/edicao` id 2919734), Negócios (`/c/negocios` id 2919736) e as
    mensagens recentes do Chat `Papo` (`/internal_api/chat_rooms/.../messages`) procurando por `query`!
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    raw_search = await page.evaluate(
        """async (args) => {
            const [qStr, incChat, defaultPapoUuid] = args;
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            const [feed1, feed2, oppPosts, chatMsgs] = await Promise.all([
                getJ('/internal_api/home_page_posts?sort=latest&page=1'),
                getJ('/internal_api/home_page_posts?sort=latest&page=2'),
                getJ('/internal_api/spaces/2919735/posts?page=1'),
                incChat ? getJ(`/internal_api/chat_rooms/${defaultPapoUuid}/messages?previous_per_page=100`) : Promise.resolve(null),
            ]);

            let allChatRecords = (chatMsgs && chatMsgs.records) || [];
            const qLow = (qStr || '').toLowerCase();
            // Pagina até 12 blocos para trás no chat Papo se ainda não achou o termo
            let curFirstId = chatMsgs ? chatMsgs.first_id : null;
            let hasPrev = Boolean(chatMsgs && chatMsgs.has_previous_page);
            for (let pageIdx = 0; pageIdx < 12 && hasPrev && curFirstId; pageIdx++) {
                const foundInCurrent = allChatRecords.some(m => ((m.body || '') + JSON.stringify(m.rich_text_body || '')).toLowerCase().includes(qLow));
                if (qLow && foundInCurrent) break;
                const prevPage = await getJ(`/internal_api/chat_rooms/${defaultPapoUuid}/messages?id=${curFirstId}&previous_per_page=100`);
                if (!prevPage || !prevPage.records || prevPage.records.length === 0) break;
                allChatRecords = [...prevPage.records, ...allChatRecords];
                curFirstId = prevPage.first_id;
                hasPrev = Boolean(prevPage.has_previous_page);
            }

            // Busca também a lista de participantes da sala para resolver participant_id -> nome / sgid / community_member_id
            const participantsResp = await getJ(`/internal_api/chat_rooms/${defaultPapoUuid}/participants?ids[]=3756169642`) ||
                                     await getJ(`/internal_api/chat_room_participants?ids[]=3756169642`) ||
                                     await getJ(`/internal_api/chat_rooms/${defaultPapoUuid}/participants`) ||
                                     await getJ(`/internal_api/mentions?query=a`);

            const allPosts = [
                ...((feed1 && feed1.records) || []),
                ...((feed2 && feed2.records) || []),
                ...((oppPosts && oppPosts.records) || []),
            ];

            return {
                origin: window.location.origin,
                posts: allPosts,
                chat_messages: allChatRecords,
                participants_raw: participantsResp,
            };
        }""",
        [query, bool(include_chat), DEFAULT_PAPO_CHAT_UUID],
    )

    q_lower = (query or "").strip().lower()
    matched_posts = []
    seen_post_ids = set()
    origin = raw_search.get("origin", "https://engenheiros-de-video.circle.so")

    for p in raw_search.get("posts") or []:
        pid = p.get("id")
        if not pid or pid in seen_post_ids:
            continue
        title = p.get("name") or ""
        body_txt = _extrair_texto_tiptap(p.get("tiptap_body")) or ""
        haystack = f"{title}\n{body_txt}".lower()
        if not q_lower or q_lower in haystack:
            seen_post_ids.add(pid)
            slug = p.get("slug") or ""
            matched_posts.append(
                {
                    "id": pid,
                    "title": title,
                    "published_at": p.get("published_at"),
                    "url": f"{origin}/c/{slug}" if slug else origin,
                    "body_excerpt": body_txt[:600],
                }
            )
            if len(matched_posts) >= limit:
                break

    matched_chats = []
    for m in raw_search.get("chat_messages") or []:
        txt = m.get("body") or _extrair_texto_tiptap(m.get("rich_text_body"))
        raw_str = json.dumps(m, ensure_ascii=False)
        if not txt and not raw_str:
            continue
        if not q_lower or q_lower in txt.lower() or q_lower in raw_str.lower():
            matched_chats.append(
                {
                    "id": m.get("id"),
                    "created_at": m.get("created_at") or m.get("sent_at"),
                    "participant_id": m.get("chat_room_participant_id"),
                    "text": txt,
                    "raw_message": m,
                }
            )

    return {
        "ok": True,
        "query": query,
        "matched_posts_count": len(matched_posts),
        "matched_posts": matched_posts,
        "matched_chat_messages_count": len(matched_chats[-limit:]),
        "matched_chat_messages": matched_chats[-limit:],
        "participants_raw": raw_search.get("participants_raw"),
    }


# ============================================================================
# 5. MEMBROS & NETWORKING / LEADS (`circle_list_members`, `circle_get_member_profile`)
# ============================================================================


async def listar_membros_comunidade(page, limit: int = 30) -> Dict[str, Any]:
    """
    Lista membros ativos da comunidade combinando autores do feed, ranking de gamificação
    (`/internal_api/gamification/members`) e salas de DM (`/internal_api/chat_rooms`).
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    res = await page.evaluate(
        """async (maxCount) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;

            async function getJ(path) {
                try {
                    const r = await fetch(path, { credentials: 'include', headers });
                    if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
                        return await r.json();
                    }
                } catch (e) {}
                return null;
            }

            const [feed, notifs, chatRooms] = await Promise.all([
                getJ('/internal_api/home_page_posts?sort=latest&page=1'),
                getJ('/internal_api/notifications'),
                getJ('/internal_api/chat_rooms'),
            ]);

            const memberIds = new Set();
            for (const p of ((feed && feed.records) || [])) {
                if (p.community_member_id) memberIds.add(p.community_member_id);
            }

            let gamificationMembers = null;
            if (memberIds.size > 0) {
                const q = Array.from(memberIds).slice(0, maxCount).map(id => `member_ids[]=${id}`).join('&');
                gamificationMembers = await getJ(`/internal_api/gamification/members?${q}`);
            }

            const actorsFromNotifs = [];
            const seenActors = new Set();
            for (const n of ((notifs && notifs.records) || [])) {
                const name = n.actor_name || (n.actor && n.actor.name) || '';
                const cmId = n.actor_community_member_id || n.community_member_id || '';
                const uid = n.actor_public_uid || (n.actor && n.actor.public_uid) || '';
                const key = name || String(cmId) || uid;
                if (key && !seenActors.has(key)) {
                    seenActors.add(key);
                    actorsFromNotifs.push({
                        name,
                        community_member_id: cmId,
                        public_uid: uid,
                        avatar_url: n.actor_avatar_url || '',
                    });
                }
            }

            return {
                active_member_ids: Array.from(memberIds),
                gamification_members: gamificationMembers,
                recent_active_members: actorsFromNotifs.slice(0, maxCount),
                direct_chat_contacts: ((chatRooms && chatRooms.records) || []).map(c => ({
                    chat_room_id: c.id,
                    chat_room_uuid: c.uuid,
                    name: c.chat_room_name,
                })),
            };
        }""",
        int(limit),
    )

    return {"ok": True, "logged_in": True, **res}


async def obter_perfil_membro(page, public_uid: str) -> Dict[str, Any]:
    """
    Puxa a ficha completa de um membro da comunidade via `/internal_api/profiles/<public_uid>?page_name=profile_view`
    (nome, headline, bio, links sociais, Instagram, localização e posts).
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    profile = await page.evaluate(
        """async (uid) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;
            try {
                const r = await fetch(`/internal_api/profiles/${uid}?page_name=profile_view`, {
                    credentials: 'include',
                    headers,
                });
                if (r.ok) {
                    const prof = await r.json();
                    let mentionData = null;
                    for (const ep of [
                        `/internal_api/mentions?query=${encodeURIComponent(prof.name || '')}`,
                        `/internal_api/rich_text/mentions?query=${encodeURIComponent(prof.name || '')}`,
                        `/internal_api/community_members/mentions?query=${encodeURIComponent(prof.name || '')}`,
                    ]) {
                        try {
                            const mr = await fetch(ep, { credentials: 'include', headers });
                            if (mr.ok && (mr.headers.get('content-type') || '').includes('json')) {
                                mentionData = await mr.json();
                                break;
                            }
                        } catch (e) {}
                    }
                    return { ok: true, profile: prof, mention_data: mentionData };
                }
                return { ok: false, status: r.status };
            } catch (e) {
                return { ok: false, error: String(e) };
            }
        }""",
        str(public_uid).strip(),
    )
    return profile


# ============================================================================
# 6. NOTIFICAÇÕES & MENÇÕES (`circle_get_notifications`)
# ============================================================================


async def obter_notificacoes(page, unread_only: bool = False, limit: int = 25) -> Dict[str, Any]:
    """
    Puxa as notificações recentes, menções `@`, comentários e novos posts seguidos via `/internal_api/notifications`.
    """
    params = await obter_parametros_pagina(page)
    if not params.get("loggedIn"):
        return {"ok": False, "logged_in": False, "message": "Não logado no Circle (porta 9363)."}

    raw_notifs = await page.evaluate(
        """async () => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const headers = { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
            if (csrf) headers['X-CSRF-Token'] = csrf;
            try {
                const r = await fetch('/internal_api/notifications', { credentials: 'include', headers });
                if (r.ok) return await r.json();
            } catch (e) {}
            return { count: 0, records: [] };
        }"""
    )

    items = []
    for n in raw_notifs.get("records") or []:
        is_unread = n.get("read_at") is None
        if unread_only and not is_unread:
            continue
        items.append(
            {
                "id": n.get("id"),
                "created_at": n.get("created_at"),
                "unread": is_unread,
                "notifiable_type": n.get("notifiable_type"),
                "notifiable_id": n.get("notifiable_id"),
                "title": n.get("notifiable_title"),
                "space_title": n.get("space_title"),
                "space_id": n.get("space_id"),
                "post_id": n.get("post_id"),
                "display_action": n.get("display_action"),
                "actor_name": n.get("actor_name") or (n.get("actor") or {}).get("name", ""),
            }
        )
        if len(items) >= limit:
            break

    return {
        "ok": True,
        "total_notifications": raw_notifs.get("count", len(items)),
        "returned_count": len(items),
        "notifications": items,
    }


# ============================================================================
# 7. DIAGNÓSTICO AUTO-HEALING (`coletar_diagnostico_pagina`)
# ============================================================================


async def coletar_diagnostico_pagina(
    page, motivo: str = "", recent_network: Optional[list] = None, take_screenshot: bool = True
) -> Dict[str, Any]:
    os.makedirs(DIAGNOSTICS_DIR, exist_ok=True)
    screenshot_path = os.path.join(DIAGNOSTICS_DIR, "last_diagnostic_screenshot.png")
    report_path = os.path.join(DIAGNOSTICS_DIR, "last_diagnostic_report.json")

    diag: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "reason": motivo,
        "selectors_file": SELECTORS_PATH,
        "api_file": os.path.abspath(__file__),
        "current_selectors": carregar_seletores(),
        "recent_network_calls": recent_network or [],
        "page_url": None,
        "params": {},
        "dom_snapshot": {},
        "selector_health": {},
        "screenshot_path": None,
    }

    if not page or page.is_closed():
        diag["error"] = "Page is closed or unavailable"
        return diag

    try:
        await injetar_bypass_e_silencio(page)
        diag["page_url"] = page.url
        diag["params"] = await obter_parametros_pagina(page)
        diag["dom_snapshot"] = await page.evaluate(
            "() => window.__MCP_CREATOR_BYPASS__.dumpInteractiveElementsForHealing(160)"
        )

        sels_map = diag["current_selectors"].get("selectors", {})
        health = {}
        for k, v in sels_map.items():
            if k == "target_url" or not isinstance(v, str):
                continue
            try:
                cnt = await page.locator(v).count()
                health[k] = {"selector": v, "matched_count": cnt, "matched": cnt > 0}
            except Exception as err:
                health[k] = {"selector": v, "matched_count": 0, "matched": False, "error": str(err)}
        diag["selector_health"] = health

        if take_screenshot:
            await page.screenshot(path=screenshot_path, full_page=False)
            diag["screenshot_path"] = screenshot_path
    except Exception as e:
        diag["collect_error"] = str(e)

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(diag, f, indent=2, ensure_ascii=False)
        diag["report_path"] = report_path
    except Exception:
        pass
    return diag
