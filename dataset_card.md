# Dataset Card: Pharmacovigilance (PV) Safety Review Dataset V2

## Overview
This is a highly curated instruction-tuning dataset designed to train Large Language Models (LLMs) to perform expert-level Pharmacovigilance (PV) medical reviews. The dataset trains models to process raw patient narratives and reference safety information (RSI) to perform four critical PV tasks:
1. Extract the primary **MedDRA Preferred Term (PT)**
2. Evaluate event **Seriousness**
3. Determine **Expectedness** (strictly based on provided safety labels)
4. Calculate **Causality** using the Naranjo algorithm.

**Total Size:** 3,000 examples formatted in OpenAI ChatML standard.

---

## Data Sources
The patient narratives and adverse events are drawn from two real-world medical data sources:
1. **openFDA (FAERS)**: Post-market surveillance reports of adverse events and medication errors submitted to the FDA. 
2. **BioDEX**: A dataset of adverse drug reactions extracted directly from published biomedical literature and case reports.

**Reference Safety Information (RSI)**:
RSI text is strictly injected into the prompts, completely eliminating the need for the model to rely on pre-trained knowledge. The safety labels are programmatically fetched from the **openFDA Drug Label API**. A robust fallback mechanism ensures OTC drugs and alternate generic names are properly mapped, achieving a **~97% label coverage rate**.

---

## Dataset Schema

Each sample in the dataset is structured as a conversation between a `system`, `user`, and `assistant`.

### 1. System Prompt
The system prompt establishes the PV persona and enforces **Strict RSI Adherence**: The model is forbidden from hallucinating external clinical knowledge and must rely *only* on the provided RSI to determine expectedness. If RSI is missing, it must output `"Cannot Evaluate"`.

### 2. User Prompt
The user prompt contains two distinct blocks of context:
* **Patient Narrative**: The raw clinical text describing the adverse event.
* **Reference Safety Information (RSI)**: The actual FDA label excerpts (Boxed Warnings, Cautions, Adverse Reactions, OTC Warnings).

### 3. Assistant Target (Output)
The model is trained to output a plain-text clinical **Chain of Thought**, followed by a strictly formatted Markdown JSON block:
```json
{
  "seriousness": {
    "is_serious": true,
    "criteria": "hospitalization"
  },
  "meddra_pt": "Cardio-respiratory arrest",
  "expectedness": "Expected",
  "causality": {
    "naranjo_score": 4,
    "interpretation": "Possible"
  }
}
```

---

## Dataset Balance & Curation
The dataset is programmatically compiled to ensure rigorous balance across multiple dimensions, preventing the model from collapsing into "always serious" or "always expected" biases.

### 1. Causality Balance
The 2,700 actual medical reviews are balanced across the three core Naranjo algorithm categories:
* **Probable / Definite** (High causal link)
* **Possible** (Moderate causal link)
* **Doubtful** (Weak or no causal link)

### 2. Edge Cases and Noise (Negative Controls)
Real-world PV systems are flooded with noise. This dataset trains the model to gracefully reject non-clinical data by including **10% (300 samples)** synthetic negative controls:
* **Administrative Noise (5%)**: Clerical notes, billing inquiries, or shipping complaints with no clinical events.
* **Missing Events (5%)**: Clinical follow-ups where no adverse events occurred.
*(Target Behavior: Output "Evaluation failed" and set seriousness to false).*

### 3. Missing RSI / Drug Mismatches
Exactly **5% (150 samples)** of the dataset consists of cases where the FDA safety label was fundamentally unavailable (e.g., discontinued drugs or foreign-only generics). 
*(Target Behavior: Evaluate seriousness and causality normally, but explicitly output `"Cannot Evaluate"` for Expectedness).*

### 4. Token Limits
To ensure efficient training and inference, the compilation script enforces strict token boundaries using the `cl100k_base` tokenizer. Outlier documents containing massive 10,000+ token narratives are systematically excluded, with a strong preference for samples under 4,000 tokens.
