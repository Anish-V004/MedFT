"""
Gradio Frontend for MedAssist App.

Layout: Two-panel
  Left  — Patient narrative input + dynamic drug list
  Right — Per-drug PV analysis cards + consolidated clinical report
"""

import gradio as gr
from backend import run_pv_assessment, generate_consolidated_report, lookup_rsi

# ─── CSS ─────────────────────────────────────────────────────────────────────
CUSTOM_CSS = """
/* ── Global ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

* { box-sizing: border-box; }

body, .gradio-container {
    font-family: 'Inter', sans-serif !important;
    background: #0d1117 !important;
    color: #e6edf3 !important;
    --block-background-fill: transparent !important;
    --block-border-color: rgba(255, 255, 255, 0.08) !important;
    --block-border-width: 0px !important;
    --block-shadow: none !important;
    --input-background-fill: #161b27 !important;
    --input-border-color: rgba(255, 255, 255, 0.08) !important;
}

/* ── App shell ── */
.app-header {
    background: linear-gradient(135deg, #1a1f2e 0%, #161b27 50%, #0d1117 100%);
    border-bottom: 1px solid rgba(56, 189, 248, 0.15);
    padding: 20px 32px;
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 0;
}

.app-header-icon {
    width: 44px;
    height: 44px;
    background: linear-gradient(135deg, #38bdf8, #818cf8);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    flex-shrink: 0;
    box-shadow: 0 0 20px rgba(56,189,248,0.25);
}

.app-title {
    font-size: 22px;
    font-weight: 700;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.2;
}

.app-subtitle {
    font-size: 13px;
    color: #8b949e;
    font-weight: 400;
    margin-top: 2px;
}

/* ── Panel labels ── */
.panel-label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #38bdf8;
    padding: 12px 0 8px 0;
    border-bottom: 1px solid rgba(56,189,248,0.12);
    margin-bottom: 16px;
}

/* ── Inputs ── */
.gradio-container textarea, .gradio-container input[type="text"] {
    background: #161b27 !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 10px !important;
    color: #e6edf3 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}

.gradio-container textarea:focus, .gradio-container input[type="text"]:focus {
    border-color: rgba(56,189,248,0.4) !important;
    box-shadow: 0 0 0 3px rgba(56,189,248,0.08) !important;
    outline: none !important;
}

/* ── Drug row ── */
.drug-row {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    margin-bottom: 6px;
}

/* ── Buttons ── */
.btn-primary {
    background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #0d1117 !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    padding: 12px 28px !important;
    cursor: pointer !important;
    box-shadow: 0 4px 24px rgba(56,189,248,0.25) !important;
    transition: all 0.2s ease !important;
    width: 100% !important;
    letter-spacing: 0.02em !important;
}

.btn-primary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 32px rgba(56,189,248,0.35) !important;
}

.btn-secondary {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    color: #8b949e !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 6px 14px !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}

.btn-secondary:hover {
    background: rgba(255,255,255,0.09) !important;
    color: #e6edf3 !important;
    border-color: rgba(255,255,255,0.2) !important;
}

.btn-clear {
    background: rgba(239,68,68,0.08) !important;
    border: 1px solid rgba(239,68,68,0.2) !important;
    border-radius: 8px !important;
    color: #f87171 !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 6px 14px !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}

.btn-clear:hover {
    background: rgba(239,68,68,0.15) !important;
    border-color: rgba(239,68,68,0.4) !important;
}

/* ── Drug analysis card ── */
.drug-card {
    background: #161b27;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s ease;
}

.drug-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
}

.drug-card:hover {
    border-color: rgba(56,189,248,0.2);
}

.drug-card-title {
    font-size: 15px;
    font-weight: 700;
    color: #e6edf3;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
}

.badge-serious    { background: rgba(239,68,68,0.15);  color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
.badge-nonserious { background: rgba(34,197,94,0.12);  color: #4ade80; border: 1px solid rgba(34,197,94,0.25); }
.badge-expected   { background: rgba(251,191,36,0.12); color: #fbbf24; border: 1px solid rgba(251,191,36,0.25); }
.badge-unexpected { background: rgba(239,68,68,0.12);  color: #f87171; border: 1px solid rgba(239,68,68,0.25); }
.badge-rsi-yes    { background: rgba(56,189,248,0.1);  color: #38bdf8; border: 1px solid rgba(56,189,248,0.2); }
.badge-rsi-no     { background: rgba(139,148,158,0.1); color: #8b949e; border: 1px solid rgba(139,148,158,0.2); }

.metric-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 14px;
}

.metric-item {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    padding: 10px 12px;
    border: 1px solid rgba(255,255,255,0.05);
}

.metric-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8b949e;
    font-weight: 600;
    margin-bottom: 4px;
}

.metric-value {
    font-size: 14px;
    font-weight: 600;
    color: #e6edf3;
}

.naranjo-score {
    font-size: 22px;
    font-weight: 700;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

.cot-section {
    background: rgba(255,255,255,0.02);
    border-left: 2px solid rgba(56,189,248,0.3);
    border-radius: 0 8px 8px 0;
    padding: 12px 14px;
    font-size: 13px;
    color: #8b949e;
    line-height: 1.6;
    font-family: 'Inter', sans-serif;
    margin-top: 10px;
}

.error-card {
    background: rgba(239,68,68,0.07);
    border: 1px solid rgba(239,68,68,0.2);
    border-radius: 10px;
    padding: 16px;
    color: #f87171;
    font-size: 13px;
    margin-bottom: 12px;
}

/* ── Consolidated report ── */
.report-section {
    background: #161b27;
    border: 1px solid rgba(129,140,248,0.2);
    border-radius: 12px;
    padding: 24px;
    margin-top: 8px;
}

.report-section h3 {
    color: #818cf8;
    font-size: 14px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid rgba(129,140,248,0.15);
    padding-bottom: 10px;
    margin-bottom: 16px;
}

/* ── Status / loading ── */
.status-bar {
    background: rgba(56,189,248,0.06);
    border: 1px solid rgba(56,189,248,0.12);
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 13px;
    color: #38bdf8;
    font-weight: 500;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* ── Scrollable output pane ── */
.output-pane {
    height: calc(100vh - 160px);
    overflow-y: auto;
    padding-right: 8px;
    scrollbar-width: thin;
    scrollbar-color: rgba(56,189,248,0.2) transparent;
}

.output-pane::-webkit-scrollbar { width: 4px; }
.output-pane::-webkit-scrollbar-thumb { background: rgba(56,189,248,0.2); border-radius: 2px; }

/* ── Divider ── */
.section-divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(129,140,248,0.25), transparent);
    margin: 24px 0;
}

/* ── Gradio overrides ── */
.gradio-container .block,
.gradio-container .form,
.gradio-container div[class*="container"],
.gradio-container div[class*="form"],
.gradio-container fieldset,
.gradio-container .contain {
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
.gradio-container label span { color: #8b949e !important; font-size: 12px !important; font-weight: 500 !important; letter-spacing: 0.04em !important; }
footer { display: none !important; }

/* ── Markdown / Report readability fixes ── */
#consolidated_report,
#consolidated_report *,
.report-section,
.report-section *,
.prose,
.prose *,
.md,
.md * {
    color: #e6edf3 !important;
}

/* Ensure table headers are readable and distinct */
.report-section th,
.prose th,
.md th {
    color: #38bdf8 !important;
    font-weight: 600 !important;
    background-color: rgba(56, 189, 248, 0.08) !important;
    border-bottom: 1px solid rgba(56, 189, 248, 0.2) !important;
}

.report-section td,
.prose td,
.md td {
    border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
}

.report-section h3 {
    color: #818cf8 !important;
}

/* ── Circular Loading UI ── */
.progress-level-inner { display: none !important; }
.progress-level {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
.progress-text::before {
    content: '';
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid rgba(56,189,248,0.2);
    border-top-color: #38bdf8;
    border-radius: 50%;
    animation: spinner 0.8s linear infinite;
    margin-right: 8px;
    vertical-align: middle;
}
@keyframes spinner { to { transform: rotate(360deg); } }
"""


# ─── HTML Renderers ──────────────────────────────────────────────────────────
def _badge(text: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{text}</span>'


def render_drug_card(result: dict, index: int) -> str:
    """Convert a per-drug result dict into an HTML card."""
    drug = result["drug"]

    if result.get("error"):
        return f"""
        <div class="drug-card error-card">
          <div class="drug-card-title">💊 Drug {index}: {drug}</div>
          <p>⚠️ Assessment failed: {result['error']}</p>
        </div>
        """

    jd = result.get("json_data") or {}
    seriousness = jd.get("seriousness", {})
    is_serious = seriousness.get("is_serious", False)
    criteria = seriousness.get("criteria", "N/A")
    meddra_pt = jd.get("meddra_pt", "N/A")
    expectedness = jd.get("expectedness", "N/A")
    causality = jd.get("causality", {})
    naranjo = causality.get("naranjo_score", "N/A")
    interp = causality.get("interpretation", "N/A")
    cot = result.get("chain_of_thought", "").strip()
    rsi_found = result.get("rsi_found", False)

    serious_badge = _badge("SERIOUS", "serious") if is_serious else _badge("NON-SERIOUS", "nonserious")
    expect_badge = (
        _badge("Expected", "expected")
        if str(expectedness).lower() == "expected"
        else _badge("Unexpected", "unexpected")
        if str(expectedness).lower() == "unexpected"
        else _badge(expectedness, "rsi-no")
    )
    rsi_badge = _badge("RSI Found", "rsi-yes") if rsi_found else _badge("RSI Missing", "rsi-no")

    # Sanitize chain-of-thought for safe HTML rendering
    cot_safe = cot.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

    return f"""
    <div class="drug-card">
      <div class="drug-card-title">
        💊 Drug {index}: {drug} &nbsp;{serious_badge}&nbsp;{rsi_badge}
      </div>
      <div class="metric-grid">
        <div class="metric-item">
          <div class="metric-label">Seriousness Criteria</div>
          <div class="metric-value">{criteria.title()}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">MedDRA PT</div>
          <div class="metric-value">{meddra_pt}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Expectedness</div>
          <div class="metric-value">{expect_badge}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Naranjo Score</div>
          <div class="naranjo-score">{naranjo}</div>
          <div class="metric-value" style="font-size:12px;color:#8b949e;">{interp}</div>
        </div>
      </div>
      <div class="cot-section">
        <strong style="color:#8b949e;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;">
          Clinical Reasoning
        </strong><br><br>
        {cot_safe}
      </div>
    </div>
    """


def render_status(msg: str) -> str:
    return f'<div class="status-bar">⚙️ {msg}</div>'


# ─── Gradio Handler ──────────────────────────────────────────────────────────
def analyse(
    narrative: str,
    drug_input: str,
    progress=gr.Progress(track_tqdm=False),
):
    """Main handler called when the Analyse button is clicked."""
    # Collect non-empty drugs by splitting on commas
    all_drugs = [d.strip() for d in drug_input.split(',') if d.strip()]

    if not narrative.strip():
        err_html = '<div class="error-card">⚠️ Please enter a patient narrative before running the analysis.</div>'
        return err_html, ""

    if not all_drugs:
        err_html = '<div class="error-card">⚠️ Please enter at least one drug name.</div>'
        return err_html, ""

    # ── Per-drug assessments ──────────────────────────────────────────────────
    per_drug_results = []
    cards_html = ""

    for i, drug in enumerate(all_drugs, 1):
        progress((i - 1) / len(all_drugs), desc=f"Assessing drug {i}/{len(all_drugs)}: {drug}…")
        result = run_pv_assessment(narrative, drug)
        per_drug_results.append(result)
        cards_html += render_drug_card(result, i)

    if len(all_drugs) == 1:
        report_md = "_A consolidated report is only generated when assessing multiple suspected drugs._"
        report_html = f'<div class="report-section" style="color:#8b949e; text-align:center;">{report_md}</div>'
    else:
        progress(len(all_drugs) / (len(all_drugs) + 1), desc="Generating consolidated report…")
        # ── Consolidated report ───────────────────────────────────────────────────
        report_md = generate_consolidated_report(narrative, per_drug_results)
        # Clean any "Prepared by:" line from report
        lines = [line for line in report_md.split('\n') if not line.strip().lower().startswith("prepared by")]
        report_md = '\n'.join(lines).strip()
        report_html = f'<div class="report-section">{report_md}</div>'

    progress(1.0, desc="Done")

    return cards_html, report_md


# ─── Gradio UI ───────────────────────────────────────────────────────────────
with gr.Blocks(title="MedAssist · PV Review Assistant") as demo:

    # Header
    gr.HTML("""
    <div class="app-header">
      <div class="app-header-icon">🧬</div>
      <div>
        <div class="app-title">MedAssist · Pharmacovigilance Review Assistant</div>
        <div class="app-subtitle">
          Fine-tuned Llama 3.3 70B & gpt-oss20b(Ollama Cloud) · Automated adverse event seriousness, expectedness & causality analysis
        </div>
      </div>
    </div>
    """)

    with gr.Column():

        # ── LEFT PANEL ────────────────────────────────────────────────────────
        with gr.Column():
            gr.HTML('<div class="panel-label">📋 Patient Narrative</div>')

            narrative_input = gr.Textbox(
                label="PATIENT NARRATIVE",
                show_label=False,
                placeholder=(
                    "Enter the full patient narrative here…\n\n"
                    "e.g. A 67-year-old male patient with hypertension presented with "
                    "sudden onset chest pain radiating to the left arm, 2 weeks after "
                    "starting aspirin and atorvastatin therapy…"
                ),
                lines=5,
                max_lines=10,
                elem_id="narrative_input",
            )

            gr.HTML('<div style="margin-top:20px; margin-bottom:8px;" class="panel-label">💊 Suspected Drugs</div>')
            gr.HTML(
                '<div style="font-size:12px;color:#8b949e;margin-bottom:12px;">'
                'Enter the names of suspected drugs, separated by commas. Each will be assessed independently '
                'against its RSI from the reference database.</div>'
            )

            drug_input = gr.Textbox(
                label="SUSPECTED DRUGS",
                show_label=False,
                placeholder="e.g. Atorvastatin, Aspirin, Metoprolol",
                elem_id="drug_input",
            )

            gr.HTML('<div style="height:20px;"></div>')

            with gr.Row():
                run_btn = gr.Button(
                    "🔬 Run PV Analysis",
                    elem_classes=["btn-primary"],
                    elem_id="run_btn",
                )
                clear_btn = gr.ClearButton(
                    components=[narrative_input, drug_input],
                    value="✕ Clear",
                    elem_classes=["btn-clear"],
                )

        # ── RIGHT PANEL ───────────────────────────────────────────────────────
        with gr.Column():
            gr.HTML('<div class="panel-label">📊 Analysis Results</div>')

            gr.HTML("""
            <div style="display:flex;gap:8px;margin-bottom:16px;">
              <span style="font-size:12px;color:#8b949e;">
                ① Each drug is assessed individually by the fine-tuned PV model against its RSI.
                &nbsp;&nbsp;②&nbsp;The base model synthesizes a consolidated clinical report.
              </span>
            </div>
            """)

            # Per-drug cards
            per_drug_html = gr.HTML(
                value=(
                    '<div style="color:#8b949e;font-size:13px;padding:40px 0;text-align:center;">'
                    '🧬 Run the analysis to see per-drug PV assessments here.</div>'
                ),
                label="Per-Drug Assessments",
                elem_id="per_drug_output",
            )

            gr.HTML('<div class="section-divider"></div>')
            gr.HTML(
                '<div style="font-size:11px;font-weight:600;letter-spacing:0.08em;'
                'text-transform:uppercase;color:#818cf8;margin-bottom:12px;">'
                '📑 Consolidated Clinical Report</div>'
            )

            # Consolidated report — using Markdown for formatted output
            consolidated_report = gr.Markdown(
                value=(
                    "_The consolidated clinical report will appear here after the analysis runs._"
                ),
                elem_id="consolidated_report",
            )

    # ─── Wire up events ────────────────────────────────────────────────────────
    run_btn.click(
        fn=analyse,
        inputs=[narrative_input, drug_input],
        outputs=[per_drug_html, consolidated_report],
        show_progress="full",
        api_name="analyse",
    )


# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from config import APP_HOST, APP_PORT, APP_SHARE, APP_TITLE
    print(f"\nStarting {APP_TITLE}")
    print(f"   Fine-tuned model endpoint : {__import__('config').FINETUNED_MODEL_BASE_URL}")
    print(f"   Base model endpoint       : {__import__('config').BASE_MODEL_BASE_URL}")
    print(f"   RSI mapping               : {__import__('config').RSI_MAPPING_PATH}\n")
    print("\n   Make sure you have added your Ollama API key to medassist_app/.env before running!")
    demo.launch(
        server_name=APP_HOST,
        server_port=APP_PORT,
        share=APP_SHARE,
        show_error=True,
        css=CUSTOM_CSS,
    )
