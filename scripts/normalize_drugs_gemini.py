import os
import sys
import json
import time
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

load_dotenv(dotenv_path=".env")

DATA_DIR = 'data'
ARCHIVE_DIR = os.path.join(DATA_DIR, 'archive')

# Ensure archive dir exists if script is run fresh
os.makedirs(ARCHIVE_DIR, exist_ok=True)

RSI_CACHE_PATH = os.path.join(DATA_DIR, 'rsi_mapping.json')
NORMALIZATION_MAP_PATH = os.path.join(ARCHIVE_DIR, 'drug_normalization_map.json')
NORMALIZED_RSI_PATH = os.path.join(ARCHIVE_DIR, 'normalized_rsi_mapping.json')

api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GEMINI_API_KEYS', '').split(',')[0]
if not api_key:
    print("Error: No GEMINI_API_KEY found.")
    sys.exit(1)

client = genai.Client(api_key=api_key)

openfda_key = os.environ.get('OPENFDA_API_KEY')
fda_delay = 0.25 if openfda_key else 1.6

class NormalizedDrug(BaseModel):
    original_name: str = Field(description="The original obscure drug name as provided.")
    normalized_name: str = Field(description="The exact US standard generic drug name or primary active ingredient. If unknown, return 'Unknown'.")

class BatchNormalization(BaseModel):
    results: list[NormalizedDrug]

def fetch_drug_rsi(drug_name, api_key=None):
    if not drug_name or drug_name.lower() == "unknown":
        return "RSI not available"
        
    base_url = 'https://api.fda.gov/drug/label.json'
    q = f'openfda.generic_name:"{drug_name}" OR openfda.brand_name:"{drug_name}" OR openfda.substance_name:"{drug_name}"'
    params = {'search': q, 'limit': 1}
    if api_key:
        params['api_key'] = api_key
        
    retries = 3
    while retries > 0:
        try:
            r = requests.get(base_url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                results = data.get('results', [])
                if results:
                    result = results[0]
                    extracted = []
                    if 'boxed_warning' in result:
                        text = result['boxed_warning']
                        extracted.append(f"BOXED WARNING:\n" + ("\n".join(text) if isinstance(text, list) else text))
                    if 'warnings_and_cautions' in result:
                        text = result['warnings_and_cautions']
                        extracted.append(f"WARNINGS AND CAUTIONS:\n" + ("\n".join(text) if isinstance(text, list) else text))
                    if 'adverse_reactions' in result:
                        text = result['adverse_reactions']
                        extracted.append(f"ADVERSE REACTIONS:\n" + ("\n".join(text) if isinstance(text, list) else text))
                        
                    if not extracted:
                        # Fallback for OTC drugs
                        if 'warnings' in result:
                            text = result['warnings']
                            extracted.append(f"OTC WARNINGS:\n" + ("\n".join(text) if isinstance(text, list) else text))
                        if 'do_not_use' in result:
                            text = result['do_not_use']
                            extracted.append(f"OTC DO NOT USE:\n" + ("\n".join(text) if isinstance(text, list) else text))
                        if 'stop_use' in result:
                            text = result['stop_use']
                            extracted.append(f"OTC STOP USE:\n" + ("\n".join(text) if isinstance(text, list) else text))
                            
                    if extracted:
                        return "\n\n".join(extracted)
                break
            elif r.status_code == 429:
                time.sleep(5)
                retries -= 1
            else:
                break
        except Exception:
            time.sleep(2)
            retries -= 1
            
    return "RSI not available"

def normalize_drug_batch(batch):
    prompt_text = (
        "Normalize the following obscure drug names, abbreviations, foreign brands, or experimental trial codes "
        "to their exact US standard generic name or primary active ingredient. If it's a combination drug, return the primary active ingredient.\n"
        "Here are the drugs to normalize:\n" + json.dumps(batch)
    )
    
    retry_count = 0
    while retry_count < 3:
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchNormalization,
                    temperature=0.0
                )
            )
            
            if response.text:
                response_json = json.loads(response.text)
                mapped_results = []
                for item in response_json.get('results', []):
                    mapped_results.append((item.get('original_name'), item.get('normalized_name', 'Unknown')))
                return mapped_results
            else:
                raise Exception("Empty response text.")
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "exhausted" in error_str.lower():
                print(f"  [API Quota/Rate Limit hit] waiting 10s...", flush=True)
                time.sleep(10)
            else:
                retry_count += 1
                time.sleep(retry_count * 2)
    return []

def main():
    print("==================================================", flush=True)
    print("DRUG NORMALIZATION (BATCHED) & RSI RE-FETCH (SEQUENTIAL)", flush=True)
    print("==================================================", flush=True)
    
    with open(RSI_CACHE_PATH, 'r', encoding='utf-8') as f:
        original_mapping = json.load(f)
        
    failed_drugs = [d for d, rsi in original_mapping.items() if rsi == "RSI not available"]
    print(f"Found {len(failed_drugs)} drugs with 'RSI not available'.", flush=True)
    
    normalization_map = {}
    if os.path.exists(NORMALIZATION_MAP_PATH):
        with open(NORMALIZATION_MAP_PATH, 'r', encoding='utf-8') as f:
            normalization_map = json.load(f)
            
    drugs_to_normalize = [d for d in failed_drugs if d not in normalization_map]
    
    if drugs_to_normalize:
        batch_size = 20
        batches = [drugs_to_normalize[i:i + batch_size] for i in range(0, len(drugs_to_normalize), batch_size)]
        print(f"\nPhase 1: Normalizing {len(drugs_to_normalize)} drugs in {len(batches)} batches...", flush=True)
        
        for idx, batch in enumerate(batches):
            results = normalize_drug_batch(batch)
            for orig, norm in results:
                if orig:
                    normalization_map[orig] = norm
            print(f" Completed batch {idx+1}/{len(batches)}. Mapped {len(results)} items.", flush=True)
            with open(NORMALIZATION_MAP_PATH, 'w', encoding='utf-8') as f:
                json.dump(normalization_map, f, indent=2, ensure_ascii=False)
                
    print(f"\nPhase 2: Fetching RSI from openFDA...", flush=True)
    new_rsi_mapping = {}
    if os.path.exists(NORMALIZED_RSI_PATH):
        with open(NORMALIZED_RSI_PATH, 'r', encoding='utf-8') as f:
            new_rsi_mapping = json.load(f)
            
    drugs_to_fetch = [d for d in failed_drugs if new_rsi_mapping.get(d, "RSI not available") == "RSI not available"]
    
    success_count = 0
    not_found_count = 0
    
    for idx, orig_drug in enumerate(drugs_to_fetch):
        norm_name = normalization_map.get(orig_drug, "Unknown")
        
        if norm_name == "Unknown" or not norm_name:
            new_rsi_mapping[orig_drug] = "RSI not available"
            not_found_count += 1
        else:
            start_t = time.time()
            rsi_text = fetch_drug_rsi(norm_name, openfda_key)
            new_rsi_mapping[orig_drug] = rsi_text
            
            if rsi_text != "RSI not available":
                success_count += 1
            else:
                not_found_count += 1
                
            elapsed = time.time() - start_t
            sleep_needed = max(0.0, fda_delay - elapsed)
            if sleep_needed > 0:
                time.sleep(sleep_needed)
                
        if (idx + 1) % 50 == 0 or (idx + 1) == len(drugs_to_fetch):
            print(f" Fetched RSI for {idx+1}/{len(drugs_to_fetch)} normalized drugs.", flush=True)
            with open(NORMALIZED_RSI_PATH, 'w', encoding='utf-8') as f:
                json.dump(new_rsi_mapping, f, indent=2, ensure_ascii=False)
                
    total_recovered = sum(1 for d, rsi in new_rsi_mapping.items() if rsi != "RSI not available")
    
    print(f"\nPhase 3: Merging recovered RSIs back into main mapping...", flush=True)
    merged_count = 0
    for orig_drug, rsi_text in new_rsi_mapping.items():
        if rsi_text != "RSI not available":
            original_mapping[orig_drug] = rsi_text
            merged_count += 1
            
    if merged_count > 0:
        with open(RSI_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(original_mapping, f, indent=2, ensure_ascii=False)
        print(f" Successfully merged {merged_count} updated RSIs into {RSI_CACHE_PATH}.", flush=True)
    else:
        print(f" No new RSIs to merge.", flush=True)

    print(f"\n==================================================", flush=True)
    print(f"DONE! Out of {len(failed_drugs)} failed drugs:", flush=True)
    print(f" Successfully recovered RSI: {total_recovered}", flush=True)
    print(f" Still not found: {len(failed_drugs) - total_recovered}", flush=True)
    print(f"==================================================", flush=True)

if __name__ == '__main__':
    main()
