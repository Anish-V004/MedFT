import os
import json
import re
import argparse
import hashlib
import pandas as pd

def check_overlap(narrative_lower, meddra_pt_lower):
    # Exact match check first
    if meddra_pt_lower in narrative_lower:
        return True
        
    # Direct word tokenization
    pt_words = re.findall(r'[a-zA-Z0-9]{3,}', meddra_pt_lower)
    narrative_words = set(re.findall(r'[a-zA-Z0-9]{2,}', narrative_lower))
    
    # Stop words to ignore
    stop_words = {'and', 'the', 'of', 'for', 'with', 'in', 'on', 'at', 'by', 'from', 'first', 'second', 'third', 'degree', 'acute', 'chronic', 'syndrome'}
    
    # Medical synonym/abbreviation mappings
    synonyms = {
        'atrioventricular': ['av'],
        'myocardial': ['mi', 'heart', 'cardiac'],
        'infarction': ['mi', 'infarct', 'attack'],
        'hemorrhage': ['bleed', 'bleeding', 'hemorrhagic'],
        'haemorrhage': ['bleed', 'bleeding', 'haemorrhagic'],
        'thrombocytopenia': ['thrombopenia', 'platelet', 'platelets'],
        'sinusoidal': ['sos', 'veno-occlusive'],
        'bradycardia': ['bradyarrhythmia', 'slow'],
        'tachycardia': ['tachyarrhythmia', 'fast'],
        'renal': ['kidney'],
        'hepatic': ['liver'],
        'cardiac': ['heart']
    }
    
    for word in pt_words:
        if word in stop_words:
            continue
        if word in narrative_words:
            return True
        # Check synonyms
        if word in synonyms:
            for syn in synonyms[word]:
                if syn in narrative_words or syn in narrative_lower:
                    return True
    return False

def clean_drug_name_for_api(drug_name):
    if not isinstance(drug_name, str) or not drug_name:
        return ""
    name = drug_name.lower().strip()
    suffixes_to_remove = [
        ' hydrochloride', ' sodium', ' calcium', ' sulfate', ' sulphate', ' phosphate', 
        ' mesylate', ' besylate', ' maleate', ' potassium', ' acetate', ' fumarate', 
        ' tartrate', ' bromide', ' iodide', ' chloride', ' gluconate', ' succinate',
        ' dl-lysine', ' dl lysine', ' medoxomil', ' tosylate', ' disodium'
    ]
    for suffix in suffixes_to_remove:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    name = name.strip('\'".,()[]{}')
    return name

def is_valid_narrative(narrative, drug):
    if not narrative or not isinstance(narrative, str):
        return False
    narrative_lower = narrative.lower()
    
    # Rule 1: Length check (at least 15 words)
    if len(narrative_lower.split()) < 15:
        return False
        
    # Rule 2: Administrative/clerical junk phrase matching
    junk_phrases = [
        "no new information",
        "medical records requested",
        "medical records not provided",
        "consumer called",
        "product quality complaint",
        "refund",
        "no additional information",
        "further information has been requested"
    ]
    for junk in junk_phrases:
        if junk in narrative_lower:
            return False
            
    # Check for empty or generic placeholder narratives
    if narrative_lower.strip() in ["blank", "unknown", "nan", "none", "n/a", "null"]:
        return False
        
    # Rule 3: Suspected drug mention check
    clean_drug = clean_drug_name_for_api(drug)
    if not clean_drug or clean_drug not in narrative_lower:
        return False
        
    return True

def extract_primary_suspected_drug(target_str, narrative_text=None):
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
    narrative = row.get('abstract') or row.get('fulltext_processed') or row.get('title') or ""
    narrative_str = str(narrative).strip()
    drug = extract_primary_suspected_drug(row.get('target', ''), narrative_str)
    return narrative_str, str(drug).strip()

def map_fda_row(row):
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

def load_narrative_to_drug_mapping():
    mapping = {}
    
    # BioDEX
    biodex_csv = 'data/biodex_cardio_clinical.csv'
    if os.path.exists(biodex_csv):
        df = pd.read_csv(biodex_csv)
        for idx, row in df.iterrows():
            narrative, drug = map_biodex_row(row)
            if narrative:
                key = hashlib.md5(narrative.encode('utf-8')).hexdigest()
                mapping[key] = drug
                
    # openFDA
    fda_csv = 'data/fda_cardio_clinical.csv'
    if os.path.exists(fda_csv):
        df = pd.read_csv(fda_csv)
        for idx, row in df.iterrows():
            narrative, drug = map_fda_row(row)
            if narrative:
                key = hashlib.md5(narrative.encode('utf-8')).hexdigest()
                mapping[key] = drug
                
    return mapping

def validate_jsonl_file(filepath, narrative_to_drug, system_prompt):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return 0, 0
        
    print(f"\nValidating dataset file: {filepath}")
    valid_records = []
    flagged_count = 0
    total_count = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            total_count += 1
            try:
                data = json.loads(line)
                messages = data.get('messages', [])
                if len(messages) < 3:
                    print(f"  [Row {idx+1}] Flagged: Missing ChatML messages (length {len(messages)}).")
                    flagged_count += 1
                    continue
                    
                # 1. System Prompt Validation
                sys_content = messages[0].get('content', '')
                if sys_content != system_prompt:
                    print(f"  [Row {idx+1}] Flagged Mismatch: Outdated system prompt.")
                    flagged_count += 1
                    continue
                    
                user_content = messages[1].get('content', '')
                assistant_content = messages[2].get('content', '')
                
                # Extract narrative
                if "\n\nReference Safety Information (RSI):" in user_content:
                    narrative = user_content.split("\n\nReference Safety Information (RSI):")[0].replace("Patient Narrative:\n", "").strip()
                else:
                    narrative = user_content.replace("Patient Narrative:\n", "").strip()
                    
                # 2. Heuristic Filter Validation (Length, Junk phrases, Drug presence)
                key = hashlib.md5(narrative.encode('utf-8')).hexdigest()
                drug = narrative_to_drug.get(key)
                if not drug:
                    print(f"  [Row {idx+1}] Flagged: Narrative not matched to any drug in current active dataset.")
                    flagged_count += 1
                    continue
                    
                if not is_valid_narrative(narrative, drug):
                    print(f"  [Row {idx+1}] Flagged Heuristic: Narrative fails 15-word threshold, contains administrative junk, or does not mention suspected drug '{drug}'.")
                    flagged_count += 1
                    continue
                    
                # Extract structured MedDRA PT from assistant response by finding JSON boundaries
                start_idx = assistant_content.find('{')
                end_idx = assistant_content.rfind('}')
                if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
                    print(f"  [Row {idx+1}] Flagged: No valid JSON boundaries found in assistant response.")
                    flagged_count += 1
                    continue
                    
                json_str = assistant_content[start_idx:end_idx+1]
                json_data = json.loads(json_str)
                meddra_pt = json_data.get('meddra_pt')
                
                if not meddra_pt:
                    print(f"  [Row {idx+1}] Flagged: Missing 'meddra_pt' field in JSON.")
                    flagged_count += 1
                    continue
                    
                # 3. Grounding / Overlap check
                if check_overlap(narrative.lower(), meddra_pt.lower()):
                    valid_records.append(line)
                else:
                    print(f"  [Row {idx+1}] Flagged Grounding Mismatch: MedDRA PT '{meddra_pt}' has no word/synonym overlap in narrative.")
                    print(f"    Narrative snippet: {narrative[:120]}...")
                    flagged_count += 1
                    
            except Exception as e:
                print(f"  [Row {idx+1}] Flagged Error: {e}")
                flagged_count += 1
                
    # Rewrite the file with only valid records if any were flagged
    if flagged_count > 0:
        print(f"  --> Cleaning file. Rewriting with {len(valid_records)} valid records (removed {flagged_count} flagged records).")
        with open(filepath, 'w', encoding='utf-8') as f_out:
            f_out.writelines(valid_records)
    else:
        print(f"  --> All {total_count} records validated successfully!")
        
    return total_count, flagged_count

def main():
    parser = argparse.ArgumentParser(description="PV Dataset Post-Generation Validation Tool.")
    parser.add_argument('--biodex', type=str, default='data/biodex_chatml.jsonl')
    parser.add_argument('--fda', type=str, default='data/fda_chatml.jsonl')
    args = parser.parse_args()
    
    print("==================================================")
    print("PHARMACOVIGILANCE DATASET VALIDATOR (LLM-AS-A-JUDGE)")
    print("==================================================")
    
    # Load mapping from narrative key to drug
    narrative_to_drug = load_narrative_to_drug_mapping()
    
    system_prompt = (
        "You are a Pharmacovigilance (PV) Medical Review Assistant. "
        "CRITICAL GROUNDING RULE: You must base your entire evaluation STRICTLY and EXCLUSIVELY on the provided Patient Narrative. "
        "Do NOT invent, hallucinate, or bring in external patient cases. Do NOT reference drugs or adverse events that are not explicitly written in the user's prompt. "
        "If the provided RSI does not match the drug in the narrative, explicitly state 'Drug Mismatch - Cannot Evaluate' in your reasoning."
    )
    
    total_validated = 0
    total_flagged = 0
    
    for path in [args.biodex, args.fda]:
        total, flagged = validate_jsonl_file(path, narrative_to_drug, system_prompt)
        total_validated += total
        total_flagged += flagged
        
    print("\n" + "="*50)
    print(f"VALIDATION REPORT SUMMARY")
    print(f"Total Evaluated: {total_validated}")
    print(f"Total Flagged & Removed: {total_flagged}")
    print(f"Total Valid & Kept: {total_validated - total_flagged}")
    print("="*50)

if __name__ == '__main__':
    main()
