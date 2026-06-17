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

---

## Complete Training Sample Example

The following is one real, end-to-end training sample from the dataset, formatted in **ChatML** (used for Llama 3 fine-tuning via Unsloth).

### Role: `system`

```text
You are a Pharmacovigilance (PV) Medical Review Assistant.

CRITICAL RULES:
1. Base your 'Expectedness' evaluation STRICTLY on the RSI (Reference Safety Information) provided in the prompt. Do NOT use your own pre-trained clinical knowledge. If the prompt states 'RSI not available', you must output 'Cannot Evaluate' for expectedness.
2. Base all other evaluations strictly on the Patient Narrative. Do not hallucinate external details.

Output a clinical Chain of Thought as plain text first, followed by a markdown JSON block containing exactly four keys: 'seriousness', 'meddra_pt', 'expectedness', and 'causality'. Do NOT include 'chain_of_thought' inside the JSON dictionary.

SCENARIOS:
Valid Case: Assess Seriousness (criteria & MedDRA PT), Expectedness (strictly via provided RSI), and Causality (Naranjo score & interpretation).

Rejection Case (Drug Mismatch / Noise): If the suspected drug in the narrative does not match the prompt's context, or the narrative lacks clinical data, explicitly state "Drug Mismatch - Cannot Evaluate" or "Evaluation failed" in your reasoning text. Then, set is_serious to false, output "N/A" for meddra_pt and expectedness, and output 0 for Naranjo score.
```

### Role: `user`

```text
Patient Narrative:
BACKGROUND
Eptifibatide is a platelet glycoprotein IIb/IIIa (GP IIb/IIIa) receptor antagonist that inhibits fibrinogen binding to the activated GP IIb/IIIa site and prevents platelet-platelet interaction and clot formation. GP IIb/IIIa inhibitors improve outcome in patients undergoing percutaneous coronary intervention for acute coronary syndrome. Thrombocytopenia is a complication of GP IIb/IIIa inhibitors, but severe thrombocytopenia is unusual. Most reported cases of severe thrombocytopenia after eptifibatide occurred in patients with acute coronary syndrome. The authors describe a patient who developed acute profound thrombocytopenia after receiving eptifibatide before emergent coronary artery bypass graft surgery.

METHODS
A 67-year-old man with a normal platelet count (220 K/uL) developed atrial fibrillation, left bundle branch block, and respiratory insufficiency consistent with acute coronary syndrome two days after colectomy. He received eptifibatide during cardiac catheterization, where three-vessel coronary artery disease was encountered. Emergent coronary artery surgery was planned, but the platelet count before surgery was 2 K/uL. Eptifibatide was discontinued, surgery was postponed, and acute coronary syndrome was treated with intraaortic balloon counterpulsation.

CONCLUSIONS
The authors describe the second reported case of eptifibatide-induced severe thrombocytopenia associated with cardiac surgery. In this case, discontinuation of eptifibatide and transfusion of apheresis platelets increased the platelet count (137 K/uL) the following day, and the patient subsequently underwent successful coronary artery surgery using cardiopulmonary bypass.

Reference Safety Information (RSI) for Eptifibatide:
5.2 Thrombocytopenia — There have been reports of acute, profound thrombocytopenia (immune-mediated and non-immune mediated) with eptifibatide. In the event of acute profound thrombocytopenia or a confirmed platelet decrease to <100,000/mm³, discontinue eptifibatide and heparin. Monitor serial platelet counts, assess the presence of drug-dependent antibodies, and treat as appropriate. Acute profound thrombocytopenia, as well as immune-mediated thrombocytopenia, have been reported in post-approval use.
```

### Role: `assistant`

```text
The patient developed acute profound thrombocytopenia (platelet count 2 K/uL) following administration of eptifibatide. The temporal association is clear — the drop occurred after drug exposure but before planned surgery. Dechallenge occurred upon discontinuation of eptifibatide, with clear clinical improvement (platelet count recovery to 137 K/uL the next day). The event is serious as it led to the postponement of emergent cardiac surgery, meeting the 'other serious medical event' criterion. Thrombocytopenia is explicitly listed in the RSI (Section 5.2), making the event 'Expected'. Naranjo scoring: +1 (previous conclusive reports in literature and RSI), +2 (event appeared after drug administration), +1 (improvement after dechallenge/discontinuation), -1 (alternative causes such as post-operative state or concurrent heparin cannot be fully excluded), +1 (objective evidence — platelet count confirmed lab result) = total of 5.

```json
{
  "seriousness": {
    "is_serious": true,
    "criteria": "other serious medical event"
  },
  "meddra_pt": "Thrombocytopenia",
  "expectedness": "Expected",
  "causality": {
    "naranjo_score": 5,
    "interpretation": "Probable"
  }
}
```
```

