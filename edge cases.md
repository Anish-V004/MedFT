# Demo Test Cases: Pharmacovigilance Review Assistant

This document contains 5 perfectly validated, clinically correct test cases selected from the 300-case test dataset (`data/pv_test_split_300.jsonl`). Use these cases in the demonstration video to showcase how the assistant handles different regulatory assessment scenarios.

---

## 1. One Drug — RSI Available Case
* **Dataset Source:** Index 1 in `data/pv_test_split_300.jsonl`
* **Suspected Drug:** `ALTEPLASE`
* **Patient Narrative:**
  > A 68 year-old male patient experienced the following adverse events: Cerebral haemorrhage; Intracranial pressure increased; Atrial fibrillation. The suspected drug is ALTEPLASE.
* **Demonstration Checkpoints:**
  * **Seriousness:** Evaluated as **Serious** (criteria: *life-threatening* or *other serious medical event*).
  * **MedDRA PT:** Identifies `Cerebral haemorrhage` (or `Intracranial haemorrhage`).
  * **Expectedness:** Evaluated as **Expected** (matches the cathflo activase/alteplase reference sheet, which lists intracranial hemorrhage as an expected trial event).
  * **Causality:** Evaluated as **Possible** (Naranjo Score: 4).

---

## 2. Multiple Drugs — RSI Available in All Cases
* **Dataset Source:** Index 15 in `data/pv_test_split_300.jsonl`
* **Suspected Drugs:** `PLAVIX, ASPIRIN`
* **Patient Narrative:**
  > A patient of unknown age male experienced the following adverse events: Multiple injuries; Cerebrovascular accident; Myocardial infarction; Haemorrhage; Ulcer haemorrhage; Gastrointestinal haemorrhage. The suspected drug is PLAVIX; ASPIRIN.
* **Demonstration Checkpoints:**
  * **Per-Drug Cards:** 
    * Displays two consecutive safety review cards (Drug 1: PLAVIX, Drug 2: ASPIRIN).
    * Both drugs are evaluated as **Serious** (hospitalization) for the primary event of interest (`Myocardial infarction`).
    * Both are marked **Unexpected** (RSI mapping for both lists bleeding/hemorrhage but not myocardial infarction).
    * Both show a **Possible** causality rating (Naranjo Score: 1).
  * **Consolidated Report:** Synthesizes a structured Markdown clinical summary table summarizing the case details, causality findings, and key pharmacovigilance actions (e.g. expedited safety report submission, signal detection for dual antiplatelet therapy, and post-marketing surveillance).

---

## 3. Multiple Drugs — Mixed RSI Availability (RSI Available in Some, Missing in Others)
* **Dataset Source:** Index 3 in `data/pv_test_split_300.jsonl`
* **Suspected Drugs:** `PROAIR HFA, INFLUENZA VACCINE`
* **Patient Narrative:**
  > A 65 year-old female patient experienced the following adverse events: Fall; Spinal compression fracture; Spinal fracture; Ventricular extrasystoles; Heart rate decreased; Weight increased; Restless legs syndrome; Blood potassium decreased; Muscle spasms. The suspected drug is PROAIR HFA; INFLUENZA VACCINE.
* **Demonstration Checkpoints:**
  * **PROAIR HFA Card:** Evaluated as **Serious** (other serious medical event), MedDRA PT: `Spinal compression fracture`, Expectedness: **Unexpected** (RSI lists hypokalemia and palpitations but not fractures), Causality: **Doubtful** (Naranjo Score: 0).
  * **INFLUENZA VACCINE Card:** Evaluated as **Serious**, MedDRA PT: `Spinal compression fracture`, Expectedness: **Cannot Evaluate** (since Reference Safety Information is not present in the local database for this vaccine), Causality: **Doubtful** (Naranjo Score: 0).
  * **Consolidated Report:** Clearly highlights the mixed RSI situation, showing `Unexpected` for Proair HFA and `Cannot Evaluate` for Influenza Vaccine side-by-side in the summary table.

---

## 4. One Drug — RSI Not Available Case
* **Dataset Source:** Index 131 in `data/pv_test_split_300.jsonl`
* **Suspected Drug:** `OLYSIO`
* **Patient Narrative:**
  > A 61 year-old female patient experienced the following adverse events: Hypothyroidism; Blood thyroid stimulating hormone decreased; Low density lipoprotein increased; Blood pressure increased. The suspected drug is OLYSIO.
* **Demonstration Checkpoints:**
  * **Seriousness:** Evaluated as **Non-Serious** (none - no hospitalization or severe outcomes reported in narrative).
  * **MedDRA PT:** Identifies `Hypothyroidism`.
  * **Expectedness:** Evaluated as **Cannot Evaluate** (since OLYSIO has no Reference Safety Information loaded in the reference mapping, trigger the fallback rule).
  * **Causality:** Evaluated as **Doubtful** (Naranjo Score: 0) or **Possible** (Naranjo Score: 1) due to minimal clinical details in the narrative.

---

## 5. Edge Case — Drug Mismatch Rejection
* **Dataset Source:** Index 50 in `data/pv_test_split_300.jsonl`
* **Suspected Drug:** `HYDROCORTISONE`
* **Patient Narrative:**
  > Despite its' life-threatening potential due to cardiac severe dysrhythmia in the context of severe hypokalemia, thyrotoxic periodic paralysis (TPP) often goes unrecognized. Although classically confined to young Asian men, it can occur irrespective of age, sex, and race. We report a short series of three cases of TPP as first presentation of Graves' disease in a young Caucasian male and in two Caucasian elderly and middle-aged women, respectively. The first patient developed malignant ventricular arrhythmias due to severe hypokalemia and was defibrillated, with recovery after prompt potassium correction and administration of antithyroid agents and propranolol. Thyroid hormone evaluation is mandatory in the presence of hypokalemic paralysis.
* **Demonstration Checkpoints:**
  * **Rejection Text:** The reasoning text clearly identifies this as a **Drug Mismatch - Cannot Evaluate** case, noting that the narrative details the use of propranolol and antithyroid agents, while the prompt evaluates the unrelated drug `Hydrocortisone`.
  * **Default Values:** Seriousness is set to **False/None**, MedDRA PT to **N/A**, Expectedness to **N/A**, and Naranjo score to **0** (Doubtful) as required by the rejection safety protocol.
