"""
HomePilot Installer — Enterprise Edition v2

Conversion-optimized installer following enterprise UX best practices:
  1. Lead with outcome, not setup
  2. Progressive disclosure (show value before asking credentials)
  3. One clear CTA
  4. Trust signals
  5. Branding consistency with ruslanmv.com/HomePilot
"""

import os
import shutil
import subprocess
import tempfile

import gradio as gr

TEMPLATE_REPO = os.environ.get("TEMPLATE_REPO", "ruslanmv/HomePilot")

# ── Core functions ───────────────────────────────────────

def validate_token(token: str):
    if not token or len(token) < 10:
        return "❌ Ingresa un token válido", ""
    try:
        import requests
        r = requests.get("https://huggingface.co/api/whoami-v2",
                         headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.ok:
            name = r.json().get("name", "")
            return f"✅ Conectado como **{name}**", name
        return f"❌ Token rechazado (HTTP {r.status_code})", ""
    except Exception as e:
        return f"❌ Error: {e}", ""


def install_space(token, username, space_name, private, model):
    if not username:
        yield "⚠️ Conecta tu cuenta primero (Paso 1)"
        return

    repo_id = f"{username}/{space_name}"
    lines = []
    def log(msg):
        lines.append(msg)
        return "\n".join(lines)

    yield log(f"▸ Creando **{repo_id}**...")

    try:
        import requests
        r = requests.post(
            "https://huggingface.co/api/repos/create",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "space", "name": space_name, "private": private, "sdk": "docker"},
            timeout=30)
        if r.ok:
            yield log("✅ Space creado")
        elif r.status_code == 409:
            yield log("✅ Space existente — actualizando")
        else:
            yield log(f"❌ Error: {r.text[:200]}")
            return

        yield log("▸ Descargando HomePilot...")
        with tempfile.TemporaryDirectory() as tmp:
            remote = f"https://user:{token}@huggingface.co/spaces/{repo_id}"
            tpl_remote = f"https://user:{token}@huggingface.co/spaces/{TEMPLATE_REPO}"

            subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                            tpl_remote, f"{tmp}/tpl"], capture_output=True, timeout=60)
            clone = subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                                    remote, f"{tmp}/sp"], capture_output=True, timeout=30)
            if clone.returncode != 0:
                os.makedirs(f"{tmp}/sp", exist_ok=True)
                subprocess.run(["git", "init", "-b", "main", f"{tmp}/sp"], capture_output=True)
                subprocess.run(["git", "-C", f"{tmp}/sp", "remote", "add", "origin", remote], capture_output=True)

            from pathlib import Path
            sp = Path(f"{tmp}/sp")
            for item in sp.iterdir():
                if item.name != ".git":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()

            yield log("▸ Configurando...")
            for item in Path(f"{tmp}/tpl").iterdir():
                if item.name == ".git": continue
                dest = sp / item.name
                shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)

            start = sp / "start.sh"
            if start.exists():
                start.write_text(start.read_text().replace(
                    "OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:1.5b}",
                    f"OLLAMA_MODEL=${{OLLAMA_MODEL:-{model}}}"))

            yield log(f"▸ Modelo: **{model}**")
            yield log("▸ Subiendo...")

            subprocess.run(["git", "lfs", "install", "--local"], capture_output=True, cwd=str(sp))
            subprocess.run(["git", "lfs", "track", "*.hpersona", "*.png", "*.webp"],
                           capture_output=True, cwd=str(sp))
            subprocess.run(["git", "-C", str(sp), "-c", "user.email=i@hp.dev",
                            "-c", "user.name=HP", "add", "-A"], capture_output=True, timeout=30)
            subprocess.run(["git", "-C", str(sp), "-c", "user.email=i@hp.dev",
                            "-c", "user.name=HP", "commit", "-m", f"HomePilot ({model})"],
                           capture_output=True, timeout=30)
            push = subprocess.run(["git", "-C", str(sp), "push", "--force", remote, "HEAD:main"],
                                  capture_output=True, text=True, timeout=120)
            if push.returncode != 0:
                yield log(f"❌ {push.stderr[:200]}")
                return

        url = f"https://huggingface.co/spaces/{repo_id}"
        yield log(f"""✅ **¡Listo!**

🔗 Tu HomePilot: [{repo_id}]({url})

**Próximos pasos:**
1. Espera ~3 min para el build
2. El modelo se descarga automáticamente
3. 14 personas AI listas para usar""")
    except Exception as e:
        yield log(f"❌ {e}")


# ── UI ───────────────────────────────────────────────────

CSS = """
/* Force dark theme on everything */
.gradio-container, .gradio-container .main { background: #09090b !important; }
footer { display: none !important; }

/* Fix Gradio Group cards to dark */
.gradio-container .gr-group, .gradio-container .gr-box,
.gradio-container .group, .gradio-container [class*="group"] {
    background: #111113 !important;
    border-color: rgba(255,255,255,0.08) !important;
}

/* Fix all inputs to dark */
.gradio-container input, .gradio-container textarea, .gradio-container select,
.gradio-container .wrap, .gradio-container .input-wrap {
    background: #09090b !important;
    border-color: rgba(255,255,255,0.1) !important;
    color: #e4e4e7 !important;
}
.gradio-container label, .gradio-container .label-wrap {
    color: #a1a1aa !important;
}

/* Fix checkbox */
.gradio-container input[type="checkbox"] {
    accent-color: #3b82f6 !important;
}

/* Dropdown */
.gradio-container .dropdown-arrow { color: #71717a !important; }
.gradio-container ul[role="listbox"] {
    background: #161618 !important;
    border-color: rgba(255,255,255,0.1) !important;
}
.gradio-container ul[role="listbox"] li {
    color: #e4e4e7 !important;
}
.gradio-container ul[role="listbox"] li:hover {
    background: rgba(59,130,246,0.15) !important;
}
"""

def build_ui():
    with gr.Blocks(css=CSS, title="HomePilot Installer", theme=gr.themes.Base(
        primary_hue="blue", neutral_hue="zinc",
    ).set(
        body_background_fill="#09090b",
        body_text_color="#e4e4e7",
        block_background_fill="#111113",
        block_border_color="rgba(255,255,255,0.08)",
        input_background_fill="#09090b",
        input_border_color="rgba(255,255,255,0.1)",
        button_primary_background_fill="linear-gradient(135deg, #06b6d4, #3b82f6, #8b5cf6)",
        button_primary_text_color="white",
        button_primary_border_color="transparent",
    )) as app:

        # ── HERO: Lead with outcome ──
        gr.HTML("""
        <div style="text-align:center; padding:48px 20px 12px; position:relative;">
            <div style="position:absolute;top:-30%;left:50%;transform:translateX(-50%);width:120%;height:100%;
                        background:radial-gradient(ellipse 60% 50% at 50% 0%, rgba(59,130,246,0.1), transparent);
                        pointer-events:none;"></div>
            <div style="position:relative;">
                <p style="font-size:48px; margin:0; line-height:1;">🏠</p>
                <h1 style="font-size:clamp(1.8rem,4vw,2.6rem); font-weight:800; letter-spacing:-0.03em;
                           margin:12px 0 0; line-height:1.15;">
                    <span style="background:linear-gradient(135deg,#06b6d4,#3b82f6,#8b5cf6);
                                 -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                        Tu IA privada en 2 minutos
                    </span>
                </h1>
                <p style="color:#71717a; font-size:15px; margin:10px auto 0; max-width:480px; line-height:1.5;">
                    Despliega HomePilot con Ollama y 14 personas AI en tu propio
                    Hugging Face Space. Sin código. Privado por defecto.
                </p>
            </div>
        </div>
        """)

        # ── TRUST SIGNALS ──
        gr.HTML("""
        <div style="display:flex; justify-content:center; gap:24px; padding:20px 0 32px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:6px; color:#a1a1aa; font-size:13px; font-weight:500;">
                <span style="color:#22c55e;">🔒</span> Privado por defecto
            </div>
            <div style="display:flex; align-items:center; gap:6px; color:#a1a1aa; font-size:13px; font-weight:500;">
                <span style="color:#3b82f6;">🧠</span> Ollama integrado
            </div>
            <div style="display:flex; align-items:center; gap:6px; color:#a1a1aa; font-size:13px; font-weight:500;">
                <span style="color:#8b5cf6;">⚡</span> GPU ready
            </div>
            <div style="display:flex; align-items:center; gap:6px; color:#a1a1aa; font-size:13px; font-weight:500;">
                <span style="color:#f59e0b;">🎭</span> 14 personas
            </div>
        </div>
        """)

        # ── STEP 1: Connect ──
        gr.HTML("""
        <div style="display:flex; align-items:center; gap:10px; padding:0 4px 8px;">
            <div style="width:28px;height:28px;border-radius:8px;
                        background:linear-gradient(135deg,#06b6d4,#3b82f6);
                        display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:800;color:white;flex-shrink:0;">1</div>
            <div>
                <div style="font-size:15px;font-weight:700;color:#e4e4e7;">Conecta tu cuenta</div>
                <div style="font-size:12px;color:#71717a;">
                    Solo necesitamos un <a href="https://huggingface.co/settings/tokens" target="_blank"
                    style="color:#3b82f6;text-decoration:none;">token de HF</a> con permiso write.
                    No almacenamos credenciales.
                </div>
            </div>
        </div>
        """)
        with gr.Group():
            with gr.Row():
                token_input = gr.Textbox(label="Token", placeholder="hf_...", type="password", scale=3)
                verify_btn = gr.Button("Conectar", variant="primary", scale=1)
            auth_status = gr.Markdown("")
            username_state = gr.State("")

        gr.HTML('<div style="height:16px"></div>')

        # ── STEP 2: Configure ──
        gr.HTML("""
        <div style="display:flex; align-items:center; gap:10px; padding:0 4px 8px;">
            <div style="width:28px;height:28px;border-radius:8px;
                        background:linear-gradient(135deg,#3b82f6,#8b5cf6);
                        display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:800;color:white;flex-shrink:0;">2</div>
            <div>
                <div style="font-size:15px;font-weight:700;color:#e4e4e7;">Configura</div>
                <div style="font-size:12px;color:#71717a;">Todo tiene valores por defecto — solo cambia si quieres.</div>
            </div>
        </div>
        """)
        with gr.Group():
            with gr.Row():
                space_name = gr.Textbox(label="Nombre", value="HomePilot", scale=2)
                private_toggle = gr.Checkbox(label="Privado", value=True, scale=1)
            model_choice = gr.Dropdown(
                label="Modelo",
                choices=[
                    ("Qwen 2.5 1.5B — rápido, ideal para empezar", "qwen2.5:1.5b"),
                    ("Qwen 2.5 3B — mejor calidad", "qwen2.5:3b"),
                    ("Llama 3 8B — poderoso (necesita GPU)", "llama3:8b"),
                    ("Gemma 2B — equilibrado", "gemma:2b"),
                ],
                value="qwen2.5:1.5b",
            )

        # ── PERSONAS PREVIEW (collapsed) ──
        with gr.Accordion("🎭 14 personas AI incluidas", open=False):
            gr.HTML("""
            <div style="padding:8px 0;">
                <p style="color:#71717a;font-size:12px;margin:0 0 12px;">
                    Se importan automáticamente al iniciar. Listas para chatear.
                </p>
                <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px;">
                    <span style="font-size:10px;font-weight:700;color:#71717a;text-transform:uppercase;
                                 letter-spacing:0.05em;width:100%;margin-bottom:4px;">Starter Pack</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🌙 LunaLite</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">😎 ChillBro</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🔍 Curiosa</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">⚡ HypeKid</span>
                </div>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                    <span style="font-size:10px;font-weight:700;color:#71717a;text-transform:uppercase;
                                 letter-spacing:0.05em;width:100%;margin-bottom:4px;">Retro Pack</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🔋 Volt</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">⚔️ Ronin</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🦖 Kaiju</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">💾 Glitch</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🗺️ Quest</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🧠 Sigma</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🃏 Loki</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🌳 OldRoot</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🔮 Morphling</span>
                    <span style="padding:5px 10px;border-radius:8px;font-size:12px;font-weight:500;
                                 color:#e4e4e7;background:#161618;border:1px solid rgba(255,255,255,0.06);">🌌 Nova</span>
                </div>
            </div>
            """)

        gr.HTML('<div style="height:16px"></div>')

        # ── STEP 3: Deploy ──
        gr.HTML("""
        <div style="display:flex; align-items:center; gap:10px; padding:0 4px 8px;">
            <div style="width:28px;height:28px;border-radius:8px;
                        background:linear-gradient(135deg,#8b5cf6,#ec4899);
                        display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:800;color:white;flex-shrink:0;">3</div>
            <div>
                <div style="font-size:15px;font-weight:700;color:#e4e4e7;">Despliega</div>
                <div style="font-size:12px;color:#71717a;">Un clic. Tu HomePilot estará listo en ~3 minutos.</div>
            </div>
        </div>
        """)
        install_btn = gr.Button("🚀 Desplegar HomePilot", variant="primary", size="lg")
        install_log = gr.Markdown("")

        # ── FOOTER ──
        gr.HTML("""
        <div style="text-align:center; padding:40px 16px 20px; border-top:1px solid rgba(255,255,255,0.06); margin-top:32px;">
            <p style="color:#52525b; font-size:12px; margin:0;">
                <a href="https://ruslanmv.com/HomePilot/" style="color:#3b82f6;text-decoration:none;">HomePilot</a> ·
                <a href="https://huggingface.co/spaces/ruslanmv/HomePilot" style="color:#3b82f6;text-decoration:none;">Template</a> ·
                <a href="https://huggingface.co/spaces/ruslanmv/Chata" style="color:#3b82f6;text-decoration:none;">Chata</a> ·
                <a href="https://github.com/ruslanmv/HomePilot" style="color:#3b82f6;text-decoration:none;">GitHub</a>
            </p>
        </div>
        """)

        # ── Events ──
        verify_btn.click(fn=validate_token, inputs=[token_input], outputs=[auth_status, username_state])
        install_btn.click(fn=install_space,
                          inputs=[token_input, username_state, space_name, private_toggle, model_choice],
                          outputs=[install_log])

    return app

if __name__ == "__main__":
    app = build_ui()
    app.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")), share=False)
