import os
import sys
import json
import time
import urllib.parse
import hashlib
import argparse
import requests
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
import re
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Reconfigure stdout to use UTF-8 to prevent console encoding errors on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Paths configuration
DATA_DIR = 'data'
RSI_CACHE_PATH = os.path.join(DATA_DIR, 'rsi_mapping.json')
BIODEX_INPUT_PATH = os.path.join(DATA_DIR, 'biodex_cardio_clinical.csv')
FDA_INPUT_PATH = os.path.join(DATA_DIR, 'fda_cardio_clinical.csv')
BIODEX_OUTPUT_PATH = os.path.join(DATA_DIR, 'biodex_chatml_v2.jsonl')
FDA_OUTPUT_PATH = os.path.join(DATA_DIR, 'fda_chatml_v2.jsonl')

# Load .env file
load_dotenv(dotenv_path=".env")

# Parse API keys for rotation
api_keys = []
keys_str = os.environ.get('GEMINI_API_KEYS') or os.environ.get('GEMINI_API_KEY')
if keys_str:
    api_keys = [k.strip() for k in re.split(r'[,;]', keys_str) if k.strip()]
    
# Also check for numbered keys: GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.
for idx in range(1, 10):
    k = os.environ.get(f'GEMINI_API_KEY_{idx}')
    if k and k.strip() and k.strip() not in api_keys:
        api_keys.append(k.strip())

if not api_keys:
    print("Error: No GEMINI_API_KEY or GEMINI_API_KEYS found in environment.")
    sys.exit(1)

def mask_key(k):
    return k[:8] + "..." + k[-4:] if len(k) > 12 else "..."

print(f"Loaded {len(api_keys)} Gemini API Key(s) for rotation: {[mask_key(k) for k in api_keys]}")

# Create thread-safe pool of clients
client_queue = queue.Queue()
for k in api_keys:
    client_queue.put(genai.Client(api_key=k))
    
# Thread-safe lock for file writing
file_lock = threading.Lock()

# Define Structured Output Schema using Pydantic
class SeriousnessDetails(BaseModel):
    is_serious: bool = Field(description="True if the event meets any regulatory seriousness criteria, False otherwise.")
    criteria: str = Field(description="The seriousness criteria met: 'death', 'hospitalization', 'life-threatening', 'disabling', 'congenital anomaly', 'other serious medical event', or 'none'.")

class CausalityDetails(BaseModel):
    naranjo_score: int = Field(description="Calculated score from Naranjo algorithm (typically between -4 and +13).")
    interpretation: str = Field(description="Causality interpretation based on Naranjo score: 'Definite' (score >= 9), 'Probable' (5-8), 'Possible' (1-4), or 'Doubtful' (<= 0).")

class PVReviewResponse(BaseModel):
    chain_of_thought: str = Field(description="Step-by-step clinical reasoning for seriousness, MedDRA term matching, expectedness, and Naranjo causality scoring.")
    seriousness: SeriousnessDetails
    meddra_pt: str = Field(description="The exact MedDRA Preferred Term (PT) for the primary adverse event (e.g., 'Myocardial infarction').")
    expectedness: str = Field(description="Expected (Labelled) or Unexpected (Unlabelled) based on whether the reaction is listed in the provided drug's RSI text.")
    causality: CausalityDetails

def clean_drug_name_for_api(drug_name):
    """Cleans raw drug names to improve match rate against openFDA label generic/brand fields."""
    if not isinstance(drug_name, str) or not drug_name:
        return ""
    name = drug_name.lower().strip()
    
    # Remove common salt/formulation suffixes
    suffixes_to_remove = [
        ' hydrochloride', ' sodium', ' calcium', ' sulfate', ' sulphate', ' phosphate', 
        ' mesylate', ' besylate', ' maleate', ' potassium', ' acetate', ' fumarate', 
        ' tartrate', ' bromide', ' iodide', ' chloride', ' gluconate', ' succinate',
        ' dl-lysine', ' dl lysine', ' medoxomil', ' tosylate', ' disodium'
    ]
    for suffix in suffixes_to_remove:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
            
    # Remove punctuation
    name = name.strip('\'".,()[]{}')
    return name

def extract_primary_suspected_drug(target_str, narrative_text=None):
    """Helper to parse suspect drug from BioDEX target text, prioritizing the one mentioned in the narrative."""
    if not isinstance(target_str, str) or not target_str:
        return "Unknown Drug"
    match = re.search(r'drugs:\s*([^:\n]+)', target_str)
    if match:
        drugs_list = [d.strip() for d in match.group(1).split(',')]
        if narrative_text and isinstance(narrative_text, str):
            for drug in drugs_list:
                clean = clean_drug_name_for_api(drug)
                if clean and clean in narrative_text.lower():
                    return drug
        if drugs_list:
            return drugs_list[0]
    return "Unknown Drug"

def map_biodex_row(row):
    """Extracts narrative and suspected drug from BioDEX row."""
    narrative = row.get('abstract') or row.get('fulltext_processed') or row.get('title') or ""
    narrative_str = str(narrative).strip()
    drug = extract_primary_suspected_drug(row.get('target', ''), narrative_str)
    return narrative_str, str(drug).strip()

def map_fda_row(row):
    """Constructs a patient narrative and suspects drug from openFDA variables."""
    age = row.get('patient_age')
    sex_val = row.get('patient_sex')
    
    sex = "unknown sex"
    if sex_val == 1.0 or sex_val == 1:
        sex = "male"
    elif sex_val == 2.0 or sex_val == 2:
        sex = "female"
        
    reactions = row.get('reactions', '')
    drugs = row.get('drugs', '')
    
    drug = "Unknown Drug"
    if isinstance(drugs, str) and drugs:
        drugs_list = [d.strip() for d in drugs.split(';')]
        if drugs_list:
            drug = drugs_list[0]
            
    # Professional narrative phrasing
    has_age = pd.notna(age)
    has_sex = (sex != "unknown sex")
    
    if has_age and has_sex:
        patient_str = f"A {int(age)} year-old {sex} patient"
    elif has_age:
        patient_str = f"A {int(age)} year-old patient of unknown sex"
    elif has_sex:
        patient_str = f"A patient of unknown age {sex}"
    else:
        patient_str = "A patient of unknown age and sex"
        
    narrative = (
        f"{patient_str} experienced the following adverse events: {reactions}. The suspected drug is {drugs}."
    )
    return narrative, drug

def load_processed_keys(output_path):
    """Loads keys of processed examples from output JSONL file to support resuming."""
    processed = set()
    if os.path.exists(output_path):
        try:
            with open(output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        messages = data.get('messages', [])
                        if len(messages) >= 2:
                            user_content = messages[1].get('content', '')
                            # Hash narrative as key
                            narrative_part = user_content.split("\n\nReference Safety Information (RSI):")[0]
                            clean_narrative = narrative_part.replace("Patient Narrative:\n", "").strip()
                            key = hashlib.md5(clean_narrative.encode('utf-8')).hexdigest()
                            processed.add(key)
        except Exception as e:
            print(f"Warning: Failed to parse existing output file {output_path} ({e}).")
    return processed

def run_dataset_pipeline(df, dataset_type, rsi_mapping, limit=None, model_name='gemini-3.1-flash-lite'):
    """Processes rows through Gemini, formats as ChatML, and appends to output files."""
    output_path = BIODEX_OUTPUT_PATH if dataset_type == 'biodex' else FDA_OUTPUT_PATH
    
    system_prompt = (
        "You are a Pharmacovigilance (PV) Medical Review Assistant.\n\n"
        "CRITICAL RULES:\n"
        "1. Base evaluations strictly on the Patient Narrative. Do not hallucinate external details.\n"
        "2. Output a clinical Chain of Thought, then a markdown JSON block containing exactly: "
        "'seriousness', 'meddra_pt', 'expectedness', and 'causality'. Do NOT include 'chain_of_thought' inside the JSON.\n\n"
        "SCENARIOS:\n"
        "1. Valid Case: Assess Seriousness (criteria & MedDRA PT), Expectedness (via RSI or label knowledge), and Causality (Naranjo score & interpretation).\n"
        "2. Drug Mismatch: State \"Drug Mismatch - Cannot Evaluate\" in reasoning. Set expectedness to \"Unexpected\" and causality to {\"naranjo_score\": 0, \"interpretation\": \"Doubtful\"}.\n"
        "3. Negative Control (Missing drug/event or noise): State \"Evaluation failed: [reason]\". Set seriousness to {\"is_serious\": false, \"criteria\": \"none\"}, meddra_pt to \"None\", expectedness to \"Unexpected\", and causality to {\"naranjo_score\": 0, \"interpretation\": \"Unassessable - Missing Data\"}."
    )
    
    processed_keys = load_processed_keys(output_path)
    
    print(f"\nProcessing {dataset_type.upper()} dataset. Outputs will be saved to '{output_path}'")
    print(f"Found {len(processed_keys)} already processed records to skip.")
    
    # Pre-calculate active rows to process (not in processed_keys and having narrative)
    active_rows = []
    for idx, row in df.iterrows():
        if dataset_type == 'biodex':
            narrative, drug = map_biodex_row(row)
        else:
            narrative, drug = map_fda_row(row)
            
        if not narrative:
            continue
            
        key = hashlib.md5(narrative.encode('utf-8')).hexdigest()
        if key in processed_keys:
            continue
            
        active_rows.append((idx, row, narrative, drug, key))
        
    total_active = len(active_rows)
    # Apply limit if any
    if limit is not None:
        active_rows = active_rows[:limit]
        total_active = len(active_rows)
        
    print(f"Total remaining rows to process in this run: {total_active}")
    
    prompt_template = """Conduct a medical safety review of the following adverse event case:

Patient Narrative:
{patient_narrative}

Reference Safety Information (RSI) for {suspected_drug}:
{rsi_text}

[INSTRUCTIONS]
Perform three tasks:
1. Seriousness Assessment: Determine if the adverse event is serious based on standard regulatory criteria (Death, Hospitalization, Life-threatening, Disabling, Congenital Anomaly, or Other medically important event). Identify the exact MedDRA Preferred Term (PT) for the primary adverse event as a text string (e.g. 'Myocardial infarction').
2. Expectedness Assessment: Compare the Patient Narrative adverse event against the provided drug's RSI text to determine if it is 'Expected' (Labelled) or 'Unexpected' (Unlabelled). If the RSI text is not available (i.e. 'RSI not available'), you must use your own pre-trained clinical medical knowledge of this drug's official label and safety profile to determine whether the event is Expected or Unexpected.
3. Causality Assessment: Evaluate the relationship between the drug and the adverse event by applying the Naranjo scale logic (evaluating temporal relationship, dechallenge improvement, alternative causes, etc.). Deduce the score and assign the interpretation: Definite (score >= 9), Probable (5-8), Possible (1-4), or Doubtful (<= 0).
"""

    count_processed = 0
    samples_shown = []
    
    def process_row(args):
        idx, row, narrative, drug, key = args
        rsi_text = rsi_mapping.get(drug, "RSI not available")
        
        prompt_text = prompt_template.format(
            suspected_drug=drug,
            patient_narrative=narrative,
            rsi_text=rsi_text
        )
        
        success = False
        retry_count = 0
        chatml_record = None
        
        while not success:
            client = client_queue.get()
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=PVReviewResponse,
                        system_instruction=system_prompt,
                    )
                )
                
                if response.text:
                    response_json = json.loads(response.text)
                    success = True
                    
                    chain_of_thought = response_json.get('chain_of_thought', '')
                    decision_data = {k: v for k, v in response_json.items() if k != 'chain_of_thought'}
                    json_block = json.dumps(decision_data, indent=2)
                    
                    assistant_content = f"{chain_of_thought}\n\n```json\n{json_block}\n```"
                    user_content = f"Patient Narrative:\n{narrative}\n\nReference Safety Information (RSI):\n{rsi_text}"
                    
                    chatml_record = {
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                            {"role": "assistant", "content": assistant_content}
                        ]
                    }
                else:
                    raise Exception("Empty response text returned.")
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "quota" in error_str.lower() or "resourceexhausted" in error_str.lower() or "exhausted" in error_str.lower()
                
                if is_rate_limit:
                    time.sleep(10)
                else:
                    retry_count += 1
                    if retry_count >= 3:
                        print(f"  Fatal Error processing drug '{drug}': {e}.")
                        break
                    time.sleep(retry_count * 5)
            finally:
                client_queue.put(client)
                
        return key, chatml_record, drug

    max_workers = max(1, len(api_keys) * 2)
    print(f"Executing {total_active} rows concurrently with {max_workers} threads across {len(api_keys)} API keys...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_row = {executor.submit(process_row, args): args for args in active_rows}
        
        for future in as_completed(future_to_row):
            key, chatml_record, drug = future.result()
            
            if chatml_record:
                with file_lock:
                    with open(output_path, 'a', encoding='utf-8') as f_out:
                        f_out.write(json.dumps(chatml_record, ensure_ascii=False) + '\n')
                        
                    count_processed += 1
                    processed_keys.add(key)
                    
                    if limit is not None and len(samples_shown) < limit:
                        samples_shown.append(chatml_record)
                        
                    left = total_active - count_processed
                    print(f" [{count_processed}/{total_active} done, {left} left] Completed review for '{drug}'")
                    
    return count_processed, samples_shown

def main():
    parser = argparse.ArgumentParser(description="PV Fine-Tuning Dataset Creator using openFDA and Gemini API (V2).")
    parser.add_argument('--limit', type=int, default=10,
                        help="Total samples to process during validation. Default is 10.")
    parser.add_argument('--full-run', action='store_true',
                        help="If set, runs the full datasets (ignores --limit).")
    parser.add_argument('--model', type=str, default='gemini-3.1-flash-lite',
                        help="Gemini model to use. Default is gemini-3.1-flash-lite.")
    parser.add_argument('--biodex', action='store_true',
                        help="Run only the BioDEX dataset.")
    parser.add_argument('--openfda', action='store_true',
                        help="Run only the openFDA dataset.")
    args = parser.parse_args()
    
    run_biodex = args.biodex or not (args.biodex or args.openfda)
    run_openfda = args.openfda or not (args.biodex or args.openfda)
    
    if not os.path.exists(BIODEX_INPUT_PATH) or not os.path.exists(FDA_INPUT_PATH):
        print(f"Error: Datasets must be built. Check paths {BIODEX_INPUT_PATH} and {FDA_INPUT_PATH}.")
        sys.exit(1)
        
    df_bio = pd.read_csv(BIODEX_INPUT_PATH)
    df_fda = pd.read_csv(FDA_INPUT_PATH)
    
    if args.full_run:
        bio_limit = None
        fda_limit = None
    else:
        if run_biodex and run_openfda:
            bio_limit = args.limit // 2
            fda_limit = args.limit - bio_limit
        elif run_biodex:
            bio_limit = args.limit
            fda_limit = 0
        elif run_openfda:
            bio_limit = 0
            fda_limit = args.limit
            
    if not os.path.exists(RSI_CACHE_PATH):
        print(f"Error: RSI cache mapping file not found at {RSI_CACHE_PATH}.")
        sys.exit(1)
        
    rsi_mapping = {}
    with open(RSI_CACHE_PATH, 'r', encoding='utf-8') as f:
        rsi_mapping = json.load(f)
        
    if run_biodex:
        run_dataset_pipeline(df_bio, 'biodex', rsi_mapping, limit=bio_limit, model_name=args.model)
    if run_openfda:
        run_dataset_pipeline(df_fda, 'openfda', rsi_mapping, limit=fda_limit, model_name=args.model)

if __name__ == '__main__':
    main()
