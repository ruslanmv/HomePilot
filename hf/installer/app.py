"""
HomePilot Installer — Hugging Face Space

A Gradio-based wizard that helps users install HomePilot into their own
private HF Space. Uses the Two-Space Architecture:

  1. THIS Space (Installer) — public, lightweight Gradio UI
  2. User's Space (Builder)  — private, Docker + Ollama + GPU

The installer:
  - Authenticates via HF token
  - Creates a new private Docker Space in the user's account
  - Pushes the HomePilot template (Dockerfile + backend + frontend + personas)
  - Guides the user to enable GPU hardware
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import gradio as gr

# ── Constants ────────────────────────────────────────────

TEMPLATE_REPO = os.environ.get("TEMPLATE_REPO", "ruslanmv/HomePilot")
DEFAULT_SPACE_NAME = "HomePilot"
BUILDER_DIR = Path(__file__).parent.parent / "builder"

# If running standalone (not inside the full repo), check local dir
if not BUILDER_DIR.exists():
    BUILDER_DIR = Path(__file__).parent / "builder"

INSTALL_STEPS = [
    {"id": "auth", "label": "Autenticación", "icon": "🔑"},
    {"id": "configure", "label": "Configuración", "icon": "⚙️"},
    {"id": "install", "label": "Instalación", "icon": "🚀"},
    {"id": "done", "label": "Listo", "icon": "✅"},
]

# ── CSS (HomePilot dark theme) ───────────────────────────

CUSTOM_CSS = """
.gradio-container {
    background: linear-gradient(135deg, #0f0a1a 0%, #1a1030 50%, #0d1117 100%) !important;
    min-height: 100vh;
}
.main-header {
    text-align: center;
    padding: 2rem 1rem;
}
.main-header h1 {
    background: linear-gradient(135deg, #a855f7, #6366f1, #22d3ee);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.5rem;
    font-weight: 900;
    letter-spacing: -0.02em;
}
.main-header p {
    color: #94a3b8;
    font-size: 0.95rem;
    margin-top: 0.5rem;
}
.step-card {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    padding: 1.5rem !important;
}
.status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.persona-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 8px;
    margin-top: 12px;
}
.persona-chip {
    background: rgba(168, 85, 247, 0.1);
    border: 1px solid rgba(168, 85, 247, 0.2);
    border-radius: 8px;
    padding: 8px 12px;
    color: #c084fc;
    font-size: 0.8rem;
    font-weight: 600;
}
"""

# ── Persona list ─────────────────────────────────────────

CHATA_PERSONAS = {
    "starter_pack": [
        "Lunalite Greeter", "Chillbro Regular",
        "Curiosa Driver", "Hypekid Reactions",
    ],
    "retro_pack": [
        "Volt Buddy", "Ronin Zero", "Rival Kaiju",
        "Glitchbyte", "Questkid 99", "Sigma Sage",
        "Wildcard Loki", "Oldroot Oracle", "Morphling X",
        "Nova Void",
    ],
}

# ── Core Functions ───────────────────────────────────────


def validate_token(token: str) -> tuple[str, str, str]:
    """Validate HF token and return (status, username, message)."""
    if not token or len(token) < 10:
        return "error", "", "❌ Token vacío o muy corto"

    try:
        result = subprocess.run(
            ["python3", "-c", f"""
import requests
r = requests.get("https://huggingface.co/api/whoami-v2",
                 headers={{"Authorization": "Bearer {token}"}}, timeout=10)
if r.ok:
    d = r.json()
    print(d.get("name", "unknown"))
else:
    print(f"ERROR:{{r.status_code}}")
"""],
            capture_output=True, text=True, timeout=15
        )
        username = result.stdout.strip()
        if username.startswith("ERROR:"):
            return "error", "", f"❌ Token inválido ({username})"
        if username:
            return "ok", username, f"✅ Autenticado como **{username}**"
        return "error", "", "❌ No pude verificar el token"
    except Exception as e:
        return "error", "", f"❌ Error: {e}"


def create_user_space(token: str, username: str, space_name: str,
                      private: bool, model: str) -> tuple[str, str]:
    """Create a new Space in the user's account and push the template."""
    repo_id = f"{username}/{space_name}"
    log_lines = []

    def log(msg):
        log_lines.append(msg)
        return "\n".join(log_lines)

    yield log(f"📦 Creando Space **{repo_id}**...")

    try:
        # Step 1: Create the Space
        import requests

        r = requests.post(
            "https://huggingface.co/api/repos/create",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "type": "space",
                "name": space_name,
                "private": private,
                "sdk": "docker",
            },
            timeout=30,
        )
        if r.ok:
            yield log("✅ Space creado")
        elif r.status_code == 409:
            yield log("⚠️ Space ya existe — actualizando")
        else:
            yield log(f"❌ Error creando Space: {r.status_code} {r.text[:200]}")
            return

        # Step 2: Clone the template
        yield log("📥 Clonando template de HomePilot...")

        with tempfile.TemporaryDirectory() as tmpdir:
            remote = f"https://user:{token}@huggingface.co/spaces/{repo_id}"

            # Try to clone existing, or init new
            clone_result = subprocess.run(
                ["git", "-c", "credential.helper=", "clone", "--depth", "1",
                 remote, tmpdir + "/space"],
                capture_output=True, text=True, timeout=30,
            )
            space_dir = tmpdir + "/space"
            if clone_result.returncode != 0:
                os.makedirs(space_dir, exist_ok=True)
                subprocess.run(["git", "init", "-b", "main", space_dir],
                               capture_output=True, timeout=10)
                subprocess.run(
                    ["git", "-C", space_dir, "remote", "add", "origin", remote],
                    capture_output=True, timeout=10,
                )

            # Wipe and copy template
            for item in Path(space_dir).iterdir():
                if item.name != ".git":
                    if item.is_dir():
                        import shutil
                        shutil.rmtree(item)
                    else:
                        item.unlink()

            yield log("📁 Copiando archivos del template...")

            # Copy from the template repo (clone it first)
            template_remote = f"https://user:{token}@huggingface.co/spaces/{TEMPLATE_REPO}"
            template_dir = tmpdir + "/template"
            subprocess.run(
                ["git", "-c", "credential.helper=", "clone", "--depth", "1",
                 template_remote, template_dir],
                capture_output=True, text=True, timeout=60,
            )

            # Copy template files to user space
            import shutil
            for item in Path(template_dir).iterdir():
                if item.name == ".git":
                    continue
                dest = Path(space_dir) / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            # Customize README with user's settings
            readme_path = Path(space_dir) / "README.md"
            if readme_path.exists():
                content = readme_path.read_text()
                content = content.replace("ruslanmv/HomePilot", repo_id)
                readme_path.write_text(content)

            yield log(f"🤖 Configurando modelo: **{model}**...")

            # Patch start.sh with custom model
            start_path = Path(space_dir) / "start.sh"
            if start_path.exists():
                content = start_path.read_text()
                content = content.replace(
                    'OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:1.5b}',
                    f'OLLAMA_MODEL=${{OLLAMA_MODEL:-{model}}}',
                )
                start_path.write_text(content)

            yield log("📤 Subiendo a Hugging Face...")

            # Setup LFS
            subprocess.run(["git", "lfs", "install", "--local"],
                           capture_output=True, cwd=space_dir, timeout=10)
            subprocess.run(
                ["git", "lfs", "track", "*.hpersona", "*.png", "*.jpg",
                 "*.webp", "*.svg", "*.woff", "*.woff2"],
                capture_output=True, cwd=space_dir, timeout=10,
            )

            # Commit and push
            subprocess.run(
                ["git", "-C", space_dir, "-c", "user.email=installer@homepilot.dev",
                 "-c", "user.name=HomePilot Installer", "add", "-A"],
                capture_output=True, timeout=30,
            )
            subprocess.run(
                ["git", "-C", space_dir, "-c", "user.email=installer@homepilot.dev",
                 "-c", "user.name=HomePilot Installer", "commit", "-m",
                 "feat: HomePilot installed via installer wizard"],
                capture_output=True, timeout=30,
            )

            push_result = subprocess.run(
                ["git", "-C", space_dir, "push", "--force", remote, "HEAD:main"],
                capture_output=True, text=True, timeout=120,
            )

            if push_result.returncode == 0:
                yield log("✅ Template subido exitosamente")
            else:
                yield log(f"❌ Error en push: {push_result.stderr[:300]}")
                return

        space_url = f"https://huggingface.co/spaces/{repo_id}"
        yield log(f"""
🎉 **¡Instalación completa!**

Tu HomePilot está en: [{repo_id}]({space_url})

**Próximos pasos:**
1. Ve a **Settings → Hardware** en tu Space
2. Selecciona **GPU (T4 small)** para mejor rendimiento
3. O déjalo en **CPU basic** (funciona pero más lento)
4. Espera ~2 min para el primer arranque (descarga modelo)

**Personas pre-instaladas:** 14 Chata personas listas para usar
""")

    except Exception as e:
        yield log(f"❌ Error inesperado: {e}")


# ── Gradio UI ────────────────────────────────────────────

def build_ui():
    with gr.Blocks(
        title="HomePilot Installer",
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(
            primary_hue="purple",
            secondary_hue="blue",
            neutral_hue="slate",
        ),
    ) as app:

        # ── Header ──────────────────────────────────
        gr.HTML("""
        <div class="main-header">
            <h1>🏠 HomePilot Installer</h1>
            <p>Instala tu propio HomePilot con IA privada en Hugging Face Spaces</p>
            <div style="margin-top: 1rem; display: flex; justify-content: center; gap: 8px;">
                <span class="persona-chip">14 Chata Personas</span>
                <span class="persona-chip">Ollama Built-in</span>
                <span class="persona-chip">GPU Ready</span>
            </div>
        </div>
        """)

        # ── Step 1: Auth ────────────────────────────
        with gr.Group(elem_classes="step-card"):
            gr.Markdown("### 🔑 Paso 1 — Autenticación")
            gr.Markdown(
                "Necesitas un [token de Hugging Face](https://huggingface.co/settings/tokens) "
                "con permisos de **write**."
            )
            with gr.Row():
                token_input = gr.Textbox(
                    label="HF Token",
                    placeholder="hf_...",
                    type="password",
                    scale=3,
                )
                verify_btn = gr.Button("Verificar", variant="primary", scale=1)
            auth_status = gr.Markdown("")
            username_state = gr.State("")

        # ── Step 2: Configure ───────────────────────
        with gr.Group(elem_classes="step-card"):
            gr.Markdown("### ⚙️ Paso 2 — Configuración")
            with gr.Row():
                space_name = gr.Textbox(
                    label="Nombre del Space",
                    value="HomePilot",
                    placeholder="HomePilot",
                    scale=2,
                )
                private_toggle = gr.Checkbox(
                    label="Privado",
                    value=True,
                    scale=1,
                )
            model_choice = gr.Dropdown(
                label="Modelo LLM",
                choices=[
                    ("Qwen 2.5 1.5B (rápido, ligero)", "qwen2.5:1.5b"),
                    ("Qwen 2.5 3B (mejor calidad)", "qwen2.5:3b"),
                    ("Llama 3 8B (poderoso, necesita GPU)", "llama3:8b"),
                    ("Gemma 2B (equilibrado)", "gemma:2b"),
                    ("Phi 3 Mini (Microsoft, compacto)", "phi3:mini"),
                ],
                value="qwen2.5:1.5b",
            )

            # Persona preview
            gr.Markdown("#### 🎭 Personas pre-instaladas")
            gr.HTML("""
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 6px; margin: 8px 0;">
                <div class="persona-chip">🌙 Lunalite</div>
                <div class="persona-chip">😎 Chillbro</div>
                <div class="persona-chip">🔍 Curiosa</div>
                <div class="persona-chip">⚡ Hypekid</div>
                <div class="persona-chip">🔋 Volt Buddy</div>
                <div class="persona-chip">⚔️ Ronin Zero</div>
                <div class="persona-chip">🦖 Rival Kaiju</div>
                <div class="persona-chip">💾 Glitchbyte</div>
                <div class="persona-chip">🗺️ Questkid 99</div>
                <div class="persona-chip">🧠 Sigma Sage</div>
                <div class="persona-chip">🃏 Wildcard Loki</div>
                <div class="persona-chip">🌳 Oldroot Oracle</div>
                <div class="persona-chip">🔮 Morphling X</div>
                <div class="persona-chip">🌌 Nova Void</div>
            </div>
            """)

        # ── Step 3: Install ─────────────────────────
        with gr.Group(elem_classes="step-card"):
            gr.Markdown("### 🚀 Paso 3 — Instalación")
            install_btn = gr.Button(
                "Instalar HomePilot →",
                variant="primary",
                size="lg",
            )
            install_log = gr.Markdown("")

        # ── Footer ──────────────────────────────────
        gr.HTML("""
        <div style="text-align: center; padding: 2rem 0; color: #64748b; font-size: 0.8rem;">
            <p>HomePilot Installer · Tu IA, tu máquina, tu privacidad</p>
            <p style="margin-top: 4px;">
                <a href="https://github.com/ruslanmv/HomePilot" style="color: #a78bfa;">GitHub</a> ·
                <a href="https://huggingface.co/spaces/ruslanmv/HomePilot" style="color: #a78bfa;">Template Space</a> ·
                <a href="https://huggingface.co/spaces/ruslanmv/Chata" style="color: #a78bfa;">Chata</a>
            </p>
        </div>
        """)

        # ── Events ──────────────────────────────────

        def on_verify(token):
            status, username, message = validate_token(token)
            return message, username

        verify_btn.click(
            fn=on_verify,
            inputs=[token_input],
            outputs=[auth_status, username_state],
        )

        install_btn.click(
            fn=create_user_space,
            inputs=[token_input, username_state, space_name,
                    private_toggle, model_choice],
            outputs=[install_log],
        )

    return app


# ── Entry point ──────────────────────────────────────────

if __name__ == "__main__":
    app = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", "7860")),
        share=False,
    )
