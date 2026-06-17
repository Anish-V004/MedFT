# MedFT · PV Review Frontend

A self-contained Gradio web application that wraps the MedFT fine-tuned Llama 3.3 70B pharmacovigilance model and a base consolidation LLM into a clean two-panel clinical review interface.

---

## Folder Contents

```
pv_frontend/
├── app.py              # Gradio UI — two-panel layout with custom dark theme
├── backend.py          # RSI lookup + fine-tuned model + base model calls
├── config.py           # Endpoint URLs, model names, generation params (edit here)
├── setup_rsi.py        # One-time script to copy rsi_mapping.json from data/
├── rsi_mapping.json    # Drug→RSI reference (copied by setup_rsi.py)
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Copy the RSI reference database
```bash
python setup_rsi.py
```
This copies `../data/rsi_mapping.json` into this folder (~23 MB).

### 3. Configure model endpoints
Edit **`config.py`** and fill in the real values:

| Setting | Description |
|---|---|
| `FINETUNED_MODEL_BASE_URL` | Base URL of the vLLM/TGI server serving the fine-tuned adapters |
| `FINETUNED_MODEL_NAME` | Model name as registered on the server |
| `BASE_MODEL_BASE_URL` | Base URL of the consolidation LLM (GPT-4o, Claude, etc.) |
| `BASE_MODEL_NAME` | Model identifier for the consolidation call |
| `BASE_MODEL_API_KEY` | API key for the consolidation model |

### 4. Launch the app
```bash
python app.py
```
Open `http://localhost:7860` in your browser.

---

## How It Works

```
User Input
 ├─ Patient Narrative
 └─ Drug 1, Drug 2, … Drug N

         ▼  For each drug:
┌─────────────────────────────────────────────────────────┐
│  1. Lookup RSI text from rsi_mapping.json                │
│  2. Build prompt: [System] + [Narrative + RSI]           │
│  3. Call fine-tuned model → chain-of-thought + JSON      │
│     {seriousness, meddra_pt, expectedness, causality}    │
└─────────────────────────────────────────────────────────┘

         ▼  After all drugs:
┌─────────────────────────────────────────────────────────┐
│  4. Bundle all per-drug findings into a single prompt    │
│  5. Call base/consolidation model → structured           │
│     Clinical PV Summary Report (Markdown)                │
└─────────────────────────────────────────────────────────┘

Output (Right Panel)
 ├─ Per-drug assessment cards (seriousness badge, MedDRA PT,
 │   expectedness, Naranjo score, clinical reasoning)
 └─ Consolidated clinical report (markdown)
```

---

## Fine-Tuned Model Serving (Example with vLLM)

```bash
# On the GPU server where adapters are saved:
pip install vllm

python -m vllm.entrypoints.openai.api_server \
  --model unsloth/Llama-3.3-70B-Instruct \
  --enable-lora \
  --lora-modules medft=./MedFT_Llama3_3_70B_16bit_adapters \
  --port 8000
```

Then set `FINETUNED_MODEL_BASE_URL = "http://<server-ip>:8000/v1"` and
`FINETUNED_MODEL_NAME = "medft"` in `config.py`.
