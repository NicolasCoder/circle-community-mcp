<div align="center">

<img src="./assets/community_cat_logo_360.png" alt="Circle Community MCP Logo" width="128" />

# 💬 Circle Community MCP (`circle-community-mcp`)

**Servidor MCP (Model Context Protocol) para comunidades no Circle.so — API interna autenticada (`/internal_api/`), TipTap JSON nativo, upload direto de capas via Rails ActiveStorage e Modo Fantasma 100% invisível no Windows.**

[![MCP Standard](https://img.shields.io/badge/MCP-FastMCP%201.2+-FF5A1F?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-1C1C1F?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Chrome CDP](https://img.shields.io/badge/Chrome%20CDP-Port%209363-2563EB?style=for-the-badge&logo=googlechrome&logoColor=white)](#arquitetura-dual-port--modo-fantasma-4-camadas)
[![SQLite Queue](https://img.shields.io/badge/SQLite%20Daemon-Port%209364-10B981?style=for-the-badge&logo=sqlite&logoColor=white)](#arquitetura-dual-port--modo-fantasma-4-camadas)
[![License: MIT](https://img.shields.io/badge/License-MIT-EFECE6?style=for-the-badge&labelColor=1C1C1F)](./LICENSE)

[Arquitetura](#-arquitetura-dual-port--modo-fantasma-4-camadas) •
[As 18 Ferramentas (7 Famílias)](#️-mapa-completo-das-18-ferramentas-7-famílias) •
[Instalação em 2 Minutos](#-como-instalar-e-usar-em-2-minutos) •
[Exemplos de Prompts](#-exemplos-reais-de-uso-prompts-prontos) •
[Auto-Healing](#-auto-healing-e-diagnóstico-dom--rede)

<br />

<img src="./assets/reference_cat_cover_style.png" alt="Engenheiros de Vídeo — Circle Community MCP" width="840" />

</div>

---

## ⚡ O Problema que o `circle-community-mcp` Resolve

Automatizar comunidades hospedadas no **Circle.so** (como a **Engenheiros de Vídeo** ou qualquer comunidade de alunos/criadores) costuma esbarrar em três barreiras:

1. **A API pública do Circle exige plano Enterprise/Admin**: membros comuns não têm chave de API para ler o feed, buscar vagas, responder comentários ou publicar seus projetos diretamente do terminal.
2. **Automação via cliques no navegador é lenta e quebra**: abrir uma janela do Playwright que rouba o foco da sua tela, esperar o editor ProseMirror carregar e simular digitação tecla por tecla leva vários segundos e falha quando o layout muda.
3. **Conflito entre múltiplos agentes**: se você estiver rodando Claude Code, Google Antigravity e Cursor ao mesmo tempo, dois processos tentando controlar o mesmo navegador corrompem o perfil do Chrome.

### Como nossa engenharia resolve isso:

O `circle-community-mcp` separa o navegador da fila de execução em **duas portas dedicadas (`9363` e `9364`)** e opera **dentro da sessão autenticada do seu navegador**, disparando chamadas HTTP diretas nos endpoints `/internal_api/` do Circle com o seu cookie e token `X-CSRF-Token`:

- **Velocidade de API com login normal de membro**: listar Spaces, ler o chat ao vivo (`Papo`), buscar vagas, dar like ou publicar um post com formatação **TipTap JSON** (incluindo links clicáveis, menções `@[Nome](url)` e upload nativo de imagem de capa via `/rails/active_storage/direct_uploads`) leva **milissegundos** em vez de dezenas de segundos clicando na tela.
- **Fallback Híbrido ProseMirror (`dom_bypass.js`)**: se algum endpoint interno do Circle exigir interação visual, o motor aciona automaticamente o fallback em DOM/Shadow-DOM e React Fiber.
- **Modo Fantasma de 4 Camadas no Windows (`Zero-Tray` + `Zero-Taskbar`)**: depois que você faz login uma única vez, o navegador roda 100% invisível em segundo plano. Ele não aparece na Barra de Tarefas, não aparece no `Alt+Tab`, não abre ícone no System Tray e nunca rouba o foco do seu teclado.

---

## 🏗️ Arquitetura Dual-Port & Modo Fantasma (4 Camadas)

O servidor foi desenhado para rodar 100% em paralelo com outros MCPs baseados em Chrome CDP (como Flow Studio `:9333/:9334`, Adobe Podcast `:9343/:9344` e AI Studio Voice `:9353/:9354`), sem colisão de portas nem vazamento de áudio.

```mermaid
flowchart LR
    subgraph Clientes["🤖 Clientes MCP (Simultâneos)"]
        A1["Claude Code CLI"]
        A2["Google Antigravity"]
        A3["Cursor IDE"]
    end

    subgraph FastMCP["⚡ circle_mcp_server.py"]
        M["FastMCP Server (18 Tools / 7 Famílias)"]
    end

    subgraph Daemon["🗄️ Fila Central (:9364)"]
        D["circle_queue_daemon.py (aiohttp HTTP)"]
        DB[("circle_queue.db (SQLite Audit & Lock)")]
        D --> DB
    end

    subgraph GhostChrome["👻 Chrome Ghost CDP (:9363)"]
        C["Perfil Isolado (C:\\circle-mcp-profile)"]
        W["Win32 Ghost Layer: SW_HIDE + WS_EX_TOOLWINDOW + DeleteTab + (-32000,-32000)"]
        S["Triple Audio Silence Shield (--mute-audio + CDP Mute + WebAudio ZeroGain)"]
        C --- W
        C --- S
    end

    subgraph Circle["🌐 Circle.so (Sessão Autenticada)"]
        API["/internal_api/* + X-CSRF-Token + TipTap JSON"]
        UP["/rails/active_storage/direct_uploads (Capas & Anexos)"]
        DOM["Fallback ProseMirror / React Fiber (dom_bypass.js)"]
    end

    A1 & A2 & A3 -->|stdio MCP| M
    M -->|HTTP JSON 127.0.0.1:9364| D
    D -->|Playwright CDP 127.0.0.1:9363| C
    C -->|In-Page Fetch (ms)| API
    C -->|Direct Upload MD5| UP
    C -.->|Auto-Fallback| DOM
```

### Por que 4 camadas no Modo Fantasma do Windows?
O Chrome precisa de uma janela de renderização real para manter sessões complexas, WebSockets de chat e tokens CSRF vivos sem throttling. Para que essa janela nunca incomode você enquanto edita vídeo ou programa, o `circleapi.py` aplica quatro travas combinadas via `user32.dll` e COM (`ITaskbarList`):

| Camada | Tecnologia Aplicada | O que faz na prática |
| :--- | :--- | :--- |
| **1. Off-Screen Coordinates** | `--window-position=-32000,-32000` | Posiciona a janela fora do espaço visível de todos os monitores desde o boot do processo. |
| **2. Remoção da Barra de Tarefas** | `ITaskbarList::DeleteTab(hwnd)` | Remove o ícone do Chrome da Barra de Tarefas do Windows (a barra fica limpa). |
| **3. Remoção do `Alt+Tab`** | `WS_EX_TOOLWINDOW` (`SetWindowLongPtrW`) | Marca a janela como ToolWindow oculta para que ela nunca apareça quando você alterna janelas com `Alt+Tab`. |
| **4. Ocultação Win32 sem Minimizar** | `ShowWindow(hwnd, SW_HIDE)` + `--disable-renderer-backgrounding` | Esconde a superfície da janela no nível do sistema operacional mantendo o motor V8 e a rede ativos a 100% da velocidade. |

> **Precisa ver o navegador para logar ou conferir algo?** Basta chamar `circle_show_browser()` (traz a janela para a coordenada `120, 80` da sua tela) e depois `circle_hide_browser()` para devolvê-la ao Modo Fantasma.

---

## 🗺️ Mapa Completo das 18 Ferramentas (7 Famílias)

O `circle-community-mcp` expõe **18 ferramentas organizadas em 7 famílias** para que o seu agente possa navegar, pesquisar, conversar, publicar e editar posts na comunidade:

### 1️⃣ Comunidades & Spaces
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_list_spaces`** | `community_url=""` | Lista os dados da comunidade logada (`/internal_api/communities`), todos os Spaces de postagem, cursos, eventos, salas de chat (`/internal_api/spaces`) e conversas de DM (`/internal_api/chat_rooms`). |

### 2️⃣ Chat Ao Vivo & Mensagens Diretas (DMs)
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_get_chat_messages`** | `chat_url_or_slug="papo"`, `limit=40` | Puxa as mensagens em tempo real do chat geral da comunidade (ex.: `Papo`) ou de qualquer sala/DM informando o nome do contato ou UUID da conversa. |
| **`circle_send_chat_message`** | `message`, `chat_url_or_slug="papo"`, `attachment_path=""` | Envia mensagem no chat ao vivo ou em uma DM via `POST /internal_api/chat_rooms/<uuid>/messages` com suporte a anexos e fallback ProseMirror. |

### 3️⃣ Feed, Postagens, Edição In-Place, Comentários & Likes
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_get_posts`** | `space_url_or_slug=""`, `limit=15` | Puxa os posts recentes do Feed Geral (`""`) ou de qualquer Space específico (`"projetos"`, `"ia"`, `"edicao"`, `"motion"`, `"negocios"`, `"clones"`, `"hyperframes"`, `"get-brolls"`). |
| **`circle_get_post_comments`** | `post_id_or_url`, `page_num=1` | Puxa a árvore completa de comentários e respostas de um post (`/internal_api/posts/<id>/comments`). |
| **`circle_create_post`** | `space_url_or_slug`, `title`, `body`, `attachment_path=""` | Cria e publica um novo post em qualquer Space. Converte quebras de linha, links `https://...` e menções `@[Nome](url)` para **TipTap JSON** nativo e faz upload da imagem de capa via Rails ActiveStorage DirectUpload. |
| **`circle_edit_post`** | `space_url_or_slug`, `post_id_or_slug`, `title=""`, `body=""`, `attachment_path=""` | **Edição In-Place (`PUT /internal_api/spaces/<space_id>/posts/<post_id>`)**: atualiza título, texto ou capa de um post já publicado sem criar post duplicado e preservando os likes e comentários existentes. |
| **`circle_comment_post`** | `post_url`, `comment_text` | Publica um comentário ou resposta em qualquer post (aceita ID numérico ou URL completa). |
| **`circle_like_post`** | `post_id_or_url` | Dá like em um post (`POST /internal_api/posts/<id>/user_likes`). |

### 4️⃣ Busca Global & Radar de Oportunidades / Vagas
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_search`** | `query`, `include_chat=True`, `limit=25` | Vasculha simultaneamente os posts do Feed, o Space de Oportunidades (`/c/motion`) e o histórico do Chat Ao Vivo (`Papo`) atrás de vagas, freelas, ferramentas ou dúvidas técnicas. |

### 5️⃣ Membros, Networking & Perfis
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_list_members`** | `limit=30` | Lista membros ativos da comunidade, contatos de DM e ranking do leaderboard (`/internal_api/gamification/members`). |
| **`circle_get_member_profile`** | `public_uid` | Puxa a ficha completa de um membro (`/internal_api/profiles/<public_uid>?page_name=profile_view`): bio, headline, redes sociais, Instagram, links, localização e pontuação. |

### 6️⃣ Notificações & Menções
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_get_notifications`** | `unread_only=False`, `limit=25` | Lista as notificações da sua conta (`/internal_api/notifications`): quem comentou no seu post, quem mencionou você com `@` e novos posts nos Spaces que você segue. |

### 7️⃣ Controle Fantasma Invisível & Auto-Healing
| Ferramenta | Parâmetros Principais | O que faz |
| :--- | :--- | :--- |
| **`circle_login_browser`** | `url="https://login.circle.so/"` | Abre e traz para a frente a janela do Chrome isolado (porta `9363`) para você fazer o login inicial na sua conta do Circle.so. |
| **`circle_hide_browser`** | *(nenhum)* | Ativa imediatamente o Modo Fantasma de 4 camadas (`SW_HIDE` + `WS_EX_TOOLWINDOW` + sem Taskbar) e salva o selo `.login_completed`. |
| **`circle_show_browser`** | *(nenhum)* | Traz a janela do Chrome (porta `9363`) de volta para a tela principal (`120, 80`) caso você queira inspecionar algo visualmente. |
| **`circle_status`** | *(nenhum)* | Retorna o status de saúde do Daemon (`:9364`), da conexão CDP (`:9363`), URL ativa, estado do login e contador de chamadas de rede. |
| **`circle_diagnose`** | `reason="manual_check"`, `take_screenshot=True` | Executa o Raio-X completo de Auto-Healing: varre DOM + Shadow-DOM, lista seletores interativos, captura as últimas 60 chamadas `/internal_api/` e tira screenshot de diagnóstico. |
| **`circle_update_selectors`** / **`circle_reload_daemon`** | `selectors={...}` | Atualiza `selectors.json` em tempo real e recarrega o módulo `circleapi.py` a quente (`importlib.reload`) sem derrubar o servidor MCP. |

---

## 🚀 Como Instalar e Usar em 2 Minutos

### Pré-requisitos
- **Python 3.10+** instalado na máquina
- **Google Chrome** instalado
- Um cliente compatível com MCP (**Claude Code**, **Google Antigravity**, **Cursor** ou **Windsurf**)

### Passo 1 — Clonar o repositório e instalar as dependências

```bash
git clone https://github.com/NicolasCoder/circle-community-mcp.git
cd circle-community-mcp
pip install -r requirements.txt
playwright install chromium
```

### Passo 2 — Rodar o Instalador Universal de 1 Clique (`setup_mcp.py`)

O script `setup_mcp.py` detecta o caminho do seu Python e registra automaticamente o servidor `circle-community` e a `SKILL.md` no **Claude Code**, **Google Antigravity** e **Cursor**:

```bash
python setup_mcp.py
```

<details>
<summary><b>🔧 Quer configurar manualmente no JSON do seu cliente MCP? (Clique para expandir)</b></summary>

Adicione o bloco abaixo no seu arquivo de configuração MCP (`~/.claude.json`, `~/.cursor/mcp.json` ou `~/.gemini/config/mcp_config.json`):

```json
{
  "mcpServers": {
    "circle-community": {
      "command": "python",
      "args": [
        "C:/caminho/para/circle-community-mcp/circle_mcp_server.py"
      ]
    }
  }
}
```
</details>

### Passo 3 — Fazer o primeiro login (`1 única vez`)

Abra o seu agente (Claude Code, Antigravity ou Cursor) e peça:

> *"Abra o navegador de login do Circle com `circle_login_browser` para eu entrar na minha conta."*

1. Uma janela limpa do Chrome (no perfil isolado `C:\circle-mcp-profile`) vai se abrir na tela de login do Circle.so.
2. Faça login normalmente na sua conta e entre na sua comunidade (ex.: `https://engenheiros-de-video.circle.so`).
3. Peça ao agente: *"Pode esconder o navegador do Circle com `circle_hide_browser`."*
4. **Pronto!** A sessão fica salva no perfil isolado e todas as próximas execuções já iniciam direto no **Modo Fantasma 100% invisível**.

---

## 💬 Exemplos Reais de Uso (Prompts Prontos)

Depois de logado, você conversa com a sua comunidade diretamente pelo chat do seu agente:

### 📦 1. Publicar um projeto novo no espaço `Projetos` (com capa e links)
> *"Publique um post no espaço `projetos` do Circle apresentando o nosso novo repositório do GitHub. Coloque um título chamativo, explique em 3 passos como a galera pode testar e anexe a imagem `./capa_projeto.png`."*

### 🔎 2. Radar de Vagas e Freelas de Edição / Motion
> *"Use o `circle_search` para buscar vagas de `editor`, `freela`, `premiere` ou `after effects` publicadas nos últimos dias no Space de Oportunidades e no chat Papo, e me traga um resumo com o link e o autor de cada uma."*

### 💬 3. Responder comentários e interagir com a galera
> *"Verifique minhas notificações recentes no Circle (`circle_get_notifications`), veja quem comentou no meu último post no espaço `projetos` e responda agradecendo e tirando as dúvidas técnicas."*

### ✏️ 4. Atualizar um post já publicado sem criar duplicata (In-Place Edit)
> *"Use `circle_edit_post` no meu post do espaço `projetos` para adicionar o link atualizado da documentação no final do texto, mantendo a imagem de capa original."*

### 🤝 5. Mapear membros e fazer networking
> *"Liste os membros mais ativos da comunidade com `circle_list_members`, puxe o perfil dos 5 primeiros com `circle_get_member_profile` e me mostre quem trabalha com Motion Design e automação com IA."*

---

## 🛡️ Auto-Healing e Diagnóstico (DOM + Rede)

Se o Circle.so atualizar algum componente visual ou rota interna no futuro, você não precisa adivinhar o que mudou:

1. Chame `circle_diagnose(reason="check_ui", take_screenshot=True)`.
2. O motor `dom_bypass.js` varre todos os elementos interativos (incluindo Shadow-DOM e editores ProseMirror/TipTap) e o sniffer de rede do daemon entrega o histórico das últimas 60 chamadas JSON em `/internal_api/`.
3. Atualize qualquer seletor em tempo real com `circle_update_selectors(...)` e aplique sem reiniciar o cliente MCP usando `circle_reload_daemon()`.

---

## 📁 Estrutura do Repositório

```text
circle-community-mcp/
├── circle_mcp_server.py     # Servidor FastMCP (expõe as 18 tools para Claude/AGY/Cursor)
├── circle_queue_daemon.py   # Daemon HTTP (:9364) + Fila Central SQLite + Sniffer de Rede
├── circleapi.py             # Motor Híbrido (/internal_api/ + TipTap JSON + ActiveStorage + Win32 Ghost Mode)
├── dom_bypass.js            # Runtime JS injetado via CDP (Shadow-DOM Piercing + React Fiber + Audio Silence Shield)
├── setup_mcp.py             # Instalador Universal 1-Clique (Antigravity, Claude Code e Cursor)
├── config.json              # Configurações de portas (9363/9364), visibilidade e timeouts
├── accounts.json            # Gerenciador de perfis isolados do Chrome (sanitizado)
├── selectors.json           # Mapa vivo de seletores DOM e endpoints monitorados pelo Auto-Healing
├── cover_style_preset.json  # Preset visual 3D Origami Cats para capas de posts na comunidade
├── SKILL.md                 # Skill oficial com instruções de uso para agentes autônomos
├── .env.example             # Variáveis de ambiente opcionais para customização de portas e perfil
├── requirements.txt         # Dependências Python (mcp, playwright, aiohttp, psutil, Pillow)
└── assets/                  # Logos e referências visuais da comunidade
```

---

## 📄 Licença

Distribuído sob a licença **MIT**. Veja [`LICENSE`](./LICENSE) para mais detalhes.

Construído por **[Nicolas Rezende (@NicolasCoder)](https://github.com/NicolasCoder)** para a comunidade **Engenheiros de Vídeo**.
