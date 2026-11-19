---
name: circle-community
description: Interage com comunidades hospedadas no Circle.so (ex: Engenheiros de Vídeo - https://engenheiros-de-video.circle.so) com 18 ferramentas em 7 famílias: (1) Comunidades & Spaces, (2) Chat Ao Vivo & DMs, (3) Feed, Postagens, Comentários & Likes, (4) Busca Global & Radar de Oportunidades/Vagas, (5) Membros & Networking/Leads, (6) Notificações & Menções, e (7) Controle Fantasma 100% Invisível (SW_HIDE + WS_EX_TOOLWINDOW + -32000,-32000 + remoção da Taskbar, sem System Tray) na porta Chrome CDP 9363 e Fila Central 9364.
---

# 💬 Circle Community MCP (`circle-community` / `circle-community-mcp`)

Servidor MCP (Model Context Protocol) construído com a arquitetura **MCP Creator — Connect Anything** para automação completa de comunidades no **Circle.so** via API interna autenticada (`/internal_api/...`) + DOM ProseMirror/TipTap.

- **Chrome CDP Isolado**: `porta 9363` (`C:\circle-mcp-profile` ou `~/.circle-mcp-profile`) — 100% em paralelo com Flow Studio (`9333`), Adobe Podcast (`9343`) e AI Studio Voice (`9353`).
- **Daemon HTTP Central**: `http://127.0.0.1:9364`
- **Modo Fantasma 4 Camadas (`Zero-Tray` + `SW_HIDE` + `WS_EX_TOOLWINDOW`)**: Remove o botão da Barra de Tarefas (`ITaskbarList::DeleteTab`), remove da lista do `Alt+Tab` (`WS_EX_TOOLWINDOW`), posiciona em `-32000,-32000` e aplica `ShowWindow(SW_HIDE)` via `user32.dll`.

---

## 🗺️ Mapa Completo das 18 Ferramentas (7 Famílias)

### 1. Comunidades & Spaces
- **`circle_list_spaces(community_url="")`**: Lista a comunidade (`/internal_api/communities`), todos os Spaces de postagem, cursos, eventos e salas de chat (`/internal_api/spaces`) e todas as DMs (`/internal_api/chat_rooms`).

### 2. Chat Ao Vivo & DMs
- **`circle_get_chat_messages(chat_url_or_slug="papo", limit=40)`**: Puxa as mensagens em tempo real do chat da comunidade (`Papo` -> `uuid: 9deb17c9-e35a-448e-8322-164241947ef8`) ou de qualquer DM (`/internal_api/chat_rooms/<uuid>/messages`).
- **`circle_send_chat_message(message, chat_url_or_slug="papo", attachment_path="")`**: Envia mensagem no chat da comunidade ou DM (`POST /internal_api/chat_rooms/<uuid>/messages` + fallback ProseMirror).

### 3. Feed, Postagens, Edição In-Place, Comentários & Likes
- **`circle_get_posts(space_url_or_slug="", limit=15)`**: Puxa os posts do Feed Geral (`""`) ou de qualquer Space (`"edicao"`, `"ia"`, `"motion"` [Oportunidades], `"negocios"`, `"get-brolls"`, `"get-brolls-hub"`, `"clones"`, `"hyperframes"`, `"projetos"`, `"conteudos"`, `"eventos"`).
- **`circle_get_post_comments(post_id_or_url, page_num=1)`**: Puxa todos os comentários de um post (`/internal_api/posts/<id>/comments`).
- **`circle_create_post(space_url_or_slug, title, body, attachment_path="")`**: Cria e publica um novo post com título, corpo TipTap/ProseMirror (com conversão automática de links `https://...` e menções `@[Nome](url)`) e upload nativo de imagem/capa via Rails ActiveStorage DirectUpload (`/rails/active_storage/direct_uploads`).
- **`circle_edit_post(space_url_or_slug, post_id_or_slug, title="", body="", attachment_path="", keep_existing_image_signed_id="")`**: **REGRA DE OURO**: Sempre que precisar atualizar, complementar ou corrigir um post já publicado, **EDITE o post existente in-place (`PUT /internal_api/posts/<id>`)** usando `circle_edit_post` em vez de criar um post novo duplicado!
- **`circle_comment_post(post_url, comment_text)`**: Comenta/responde em um post existente.
- **`circle_like_post(post_id_or_url)`**: Dá like em um post (`POST /internal_api/posts/<id>/user_likes`).

---

## 🎨 PADRÃO OFICIAL DE IMAGEM DE CAPA — GATINHOS ORIGAMI `ENGENHEIROS DE VÍDEO` (`cover_style_preset.json`)

Para postagens na comunidade `Engenheiros de Vídeo` com imagem de capa gerada por IA, consulte [`cover_style_preset.json`](./cover_style_preset.json):
1. **Ingredientes Visuais (`assets/`)**:
   - [`./assets/community_cat_logo_360.png`](./assets/community_cat_logo_360.png)
   - [`./assets/reference_cat_cover_style.png`](./assets/reference_cat_cover_style.png)
2. **Estética & DNA Visual**:
   - Os **3 gatinhos mascotes geométricos low-poly / origami da comunidade** (o gatinho cinza-chumbo rabugento, o gatinho laranja vibrante com olhos `> . <` e o gatinho creme-e-laranja sorridente) como bonecos 3D táteis foscos em cima de uma bancada de engenharia de vídeo creme editorial (`#EFECE6` a `#FAF8F4`, com base de corte quadriculada escura e blueprint técnico nas bordas), interagindo com um **objeto tecnológico gigante** do tema do post em preto fosco (`#1C1C1F`) e laranja vibrante (`#FF5A1F`)!
   - **Template de Prompt**:
     ```text
     A charismatic 16:9 editorial illustration and tactile 3D studio scene featuring the cute geometric origami-style orange, cream-and-orange, and charcoal-gray mascot cats from the reference image, standing proudly on a warm cream minimalist engineering desk (#EFECE6 background, dark cutting mat grid and blueprint on the sides) and interacting triumphantly with {HERO_OBJECT_DESCRIPTION} in matte-black (#1C1C1F) and vibrant-orange (#FF5A1F) accents. Clean warm editorial studio lighting, ultra-crisp tactile low-poly designer figure aesthetic matching the reference image, playful modern video-engineering community cover art, no text or watermarks.
     ```

### 4. Busca Global & Radar de Oportunidades / Vagas
- **`circle_search(query, include_chat=True, limit=25)`**: Vasculha simultaneamente o Feed, o Space de Oportunidades (`/c/motion`) e o Chat Ao Vivo (`Papo`) buscando termos, vagas, freelas ou dúvidas.

### 5. Membros & Networking / Leads
- **`circle_list_members(limit=30)`**: Lista membros ativos, contatos de DM e ranking de gamificação (`/internal_api/gamification/members`).
- **`circle_get_member_profile(public_uid)`**: Puxa a ficha completa de um membro (`/internal_api/profiles/<public_uid>?page_name=profile_view` com bio, headline, redes sociais e links).

### 6. Notificações & Menções
- **`circle_get_notifications(unread_only=False, limit=25)`**: Puxa as notificações da conta (`/internal_api/notifications`): respostas, menções `@` e novos posts.

### 7. Controle Fantasma & Auto-Healing
- **`circle_hide_browser()`** / **`circle_show_browser()`** / **`circle_login_browser()`**
- **`circle_status()`** / **`circle_diagnose()`** / **`circle_update_selectors()`** / **`circle_reload_daemon()`**
