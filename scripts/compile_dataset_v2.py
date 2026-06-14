import os
import json
import random
import sys
import argparse
import pandas as pd
import numpy as np
import tiktoken

# Ensure UTF-8 printing on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Optimized, concise scenario-based System Prompt
SYSTEM_PROMPT = (
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

ADMIN_NOISE_TEMPLATES = [
    "Consumer called to ask for a refund for their prescription of {drug}. The package was damaged during shipping.",
    "Medical records were requested for the patient taking {drug} but they have not been provided by the clinical site.",
    "Follow-up report for patient on {drug}: No new clinical information has been received at this time.",
    "Product quality complaint: The customer noticed a discolored tablet in the bottle of {drug}. No adverse events reported.",
    "Customer called to request a replacement bottle of {drug} because they misplaced their current medication.",
    "Administrative notice: The patient on {drug} requested to be removed from the pharmacy mailing list.",
    "Insurance billing inquiry: Customer called to check co-pay pricing details for {drug}."
]

def calculate_tokens(sample, enc):
    """Calculates the ChatML formatted token size of a sample."""
    messages = sample.get('messages', [])
    full_text = ""
    for msg in messages:
        full_text += f"<|im_start|>{msg.get('role', '')}\n{msg.get('content', '')}<|im_end|>\n"
    return len(enc.encode(full_text))

def parse_valid_review(sample, enc):
    """Parses a valid ChatML review to extract its metrics, token count, and mismatch status."""
    messages = sample.get('messages', [])
    if len(messages) < 3:
        return None
        
    user_content = messages[1].get('content', '')
    assistant_content = messages[2].get('content', '')
    
    # Identify source
    source = 'openfda' if 'The suspected drug is' in user_content and 'experienced the following adverse events' in user_content else 'biodex'
    
    # Check RSI availability
    rsi_avail = 'RSI not available' not in user_content
    
    # Check if this is a mismatch case
    is_mismatch = "drug mismatch" in assistant_content.lower() or "cannot evaluate" in assistant_content.lower()
    
    # Extract JSON block
    start_idx = assistant_content.find('{')
    end_idx = assistant_content.rfind('}')
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None
        
    try:
        json_data = json.loads(assistant_content[start_idx:end_idx+1])
        expectedness = json_data.get('expectedness', 'Unexpected')
        causality = json_data.get('causality', {})
        naranjo = causality.get('naranjo_score', 1)
        
        # Categorize Naranjo
        if naranjo <= 0:
            causality_cat = 'Doubtful'
        elif 1 <= naranjo <= 4:
            causality_cat = 'Possible'
        else:
            causality_cat = 'Probable/Definite'
            
        tokens = calculate_tokens(sample, enc)
            
        return {
            'sample': sample,
            'source': source,
            'expectedness': expectedness,
            'causality_cat': causality_cat,
            'rsi_avail': rsi_avail,
            'is_mismatch': is_mismatch,
            'tokens': tokens
        }
    except Exception:
        return None

def generate_negative_cases(count_per_cat=100):
    """Programmatically generates diversified negative escalation samples (V2 - Uniform Schema)."""
    samples = []
    
    # Load raw datasets to grab realistic demographics, reactions, and drugs
    fda_drugs = ["Lisinopril", "Aspirin", "Humira", "Atorvastatin", "Metoprolol", "Furosemide", "Soliris", "Amlodipine"]
    fda_reactions = ["Myocardial infarction", "Renal failure acute", "Thrombocytopenia", "Cardiac arrest", "Angina pectoris"]
    
    if os.path.exists('data/fda_cardio_clinical.csv'):
        try:
            df = pd.read_csv('data/fda_cardio_clinical.csv', nrows=100)
            if not df.empty:
                fda_drugs = [d.split(';')[0].strip() for d in df['drugs'].dropna() if d]
                fda_reactions = [r.split(';')[0].strip() for r in df['reactions'].dropna() if r]
        except Exception:
            pass
            
    # 1. Missing Drugs
    for i in range(count_per_cat):
        age = random.randint(18, 85)
        sex = random.choice(["male", "female"])
        reaction = random.choice(fda_reactions)
        
        narrative = f"A {age} year-old {sex} patient experienced the following adverse events: {reaction}. The suspect medication was not documented in the safety report."
        rsi_text = "RSI not available"
        
        chain_of_thought = "Evaluation failed: The patient narrative does not mention any suspect medication. A clinical pharmacovigilance review cannot be performed without identifying the administered drug."
        assistant_json = {
            "seriousness": {
                "is_serious": True,
                "criteria": "other serious medical event"
            },
            "meddra_pt": "None",
            "expectedness": "Unexpected",
            "causality": {
                "naranjo_score": 0,
                "interpretation": "Unassessable - Missing Data"
            }
        }
        
        user_content = f"Patient Narrative:\n{narrative}\n\nReference Safety Information (RSI):\n{rsi_text}"
        # Format assistant message with Chain of Thought on top, followed by 4-key JSON block (no chain_of_thought key inside JSON)
        assistant_content = f"{chain_of_thought}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
        samples.append({
            "category": "Missing Drug",
            "sample": {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": assistant_content}
                ]
            }
        })

    # 2. Missing Events
    for i in range(count_per_cat):
        age = random.randint(18, 85)
        sex = random.choice(["male", "female"])
        drug = random.choice(fda_drugs)
        
        narrative = f"A {age} year-old {sex} patient was prescribed {drug} for cardiovascular therapy. No adverse events, complaints, or physical symptoms were reported during the follow-up period."
        rsi_text = f"BOXED WARNING:\nWARNING: Serious events are possible.\n\nWARNINGS AND CAUTIONS:\nMonitor patient closely.\n\nADVERSE REACTIONS:\nHeadache, nausea."
        
        chain_of_thought = "Evaluation failed: The patient narrative does not describe any adverse events or reactions. A safety assessment cannot be completed without a reported reaction."
        assistant_json = {
            "seriousness": {
                "is_serious": False,
                "criteria": "none"
            },
            "meddra_pt": "None",
            "expectedness": "Unexpected",
            "causality": {
                "naranjo_score": 0,
                "interpretation": "Unassessable - Missing Data"
            }
        }
        
        user_content = f"Patient Narrative:\n{narrative}\n\nReference Safety Information (RSI):\n{rsi_text}"
        assistant_content = f"{chain_of_thought}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
        samples.append({
            "category": "Missing Event",
            "sample": {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": assistant_content}
                ]
            }
        })

    # 3. Administrative Noise
    for i in range(count_per_cat):
        drug = random.choice(fda_drugs)
        template = random.choice(ADMIN_NOISE_TEMPLATES)
        narrative = template.format(drug=drug)
        rsi_text = "RSI not available"
        
        chain_of_thought = f"Evaluation failed: The text contains only administrative or clerical metadata ('{narrative.split('.')[0].lower()}') and does not describe a clinical patient case. No safety review can be concluded."
        assistant_json = {
            "seriousness": {
                "is_serious": False,
                "criteria": "none"
            },
            "meddra_pt": "None",
            "expectedness": "Unexpected",
            "causality": {
                "naranjo_score": 0,
                "interpretation": "Unassessable - Missing Data"
            }
        }
        
        user_content = f"Patient Narrative:\n{narrative}\n\nReference Safety Information (RSI):\n{rsi_text}"
        assistant_content = f"{chain_of_thought}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
        samples.append({
            "category": "Administrative Noise",
            "sample": {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": assistant_content}
                ]
            }
        })

    return samples

def main():
    parser = argparse.ArgumentParser(description="PV Dataset Compiler V2: Enforces uniform schema and mismatch limits.")
    parser.add_argument('--output', type=str, default='data/pv_safety_review_dataset_3000_v2.jsonl',
                        help="Path to save the new v2 compiled dataset.")
    parser.add_argument('--max-tokens', type=int, default=6000,
                        help="Hard maximum token count limit (default 6000).")
    parser.add_argument('--pref-tokens', type=int, default=4000,
                        help="Preferred maximum token count limit (default 4000).")
    parser.add_argument('--max-mismatch', type=int, default=150,
                        help="Maximum drug mismatch cases to allow in the dataset.")
    args = parser.parse_args()
    
    print("==================================================")
    print("PHARMACOVIGILANCE DATASET COMPILER V2")
    print("==================================================")
    
    enc = tiktoken.get_encoding("cl100k_base")
    random.seed(42)  # Set seed for reproducibility
    
    # 1. Load existing reviews from the two generated sources
    valid_pool = []
    for fpath in ['data/biodex_chatml.jsonl', 'data/fda_chatml.jsonl']:
        if os.path.exists(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        # Parse sample and replace system prompt with updated V2 prompt
                        raw_sample = json.loads(line)
                        if 'messages' in raw_sample and len(raw_sample['messages']) > 0:
                            raw_sample['messages'][0]['content'] = SYSTEM_PROMPT
                            
                        parsed = parse_valid_review(raw_sample, enc)
                        if parsed:
                            valid_pool.append(parsed)
                            
    print(f"Loaded {len(valid_pool)} valid reviews from source pools.")
    
    # Filter by hard token limit
    filtered_pool = [r for r in valid_pool if r['tokens'] <= args.max_tokens]
    print(f"Pool size after excluding samples > {args.max_tokens} tokens: {len(filtered_pool)}")
    
    # 2. Partition into Aligned and Mismatch pools
    aligned_pool = [r for r in filtered_pool if not r['is_mismatch']]
    mismatch_pool = [r for r in filtered_pool if r['is_mismatch']]
    
    print(f"  - Aligned reviews available: {len(aligned_pool)}")
    print(f"  - Drug Mismatch reviews available: {len(mismatch_pool)}")
    
    # 3. Select mismatch cases (target exactly args.max_mismatch)
    num_mismatch_to_select = min(len(mismatch_pool), args.max_mismatch)
    # Prioritize shorter mismatch cases under preferred tokens first
    mismatch_under_pref = [r for r in mismatch_pool if r['tokens'] <= args.pref_tokens]
    mismatch_above_pref = [r for r in mismatch_pool if r['tokens'] > args.pref_tokens]
    
    selected_mismatch = []
    if len(mismatch_under_pref) >= num_mismatch_to_select:
        selected_mismatch = random.sample(mismatch_under_pref, num_mismatch_to_select)
    else:
        selected_mismatch = list(mismatch_under_pref)
        needed = num_mismatch_to_select - len(selected_mismatch)
        selected_mismatch += random.sample(mismatch_above_pref, needed)
        
    print(f"Selected {len(selected_mismatch)} drug mismatch cases (max limit: {args.max_mismatch})")
    
    # 4. Select aligned cases to reach exactly 2,700 total medical reviews
    target_medical_reviews = 2700
    target_aligned = target_medical_reviews - len(selected_mismatch) # 2550
    
    # Separate aligned pool by Naranjo category
    aligned_cats = {
        'Doubtful': [r for r in aligned_pool if r['causality_cat'] == 'Doubtful'],
        'Possible': [r for r in aligned_pool if r['causality_cat'] == 'Possible'],
        'Probable/Definite': [r for r in aligned_pool if r['causality_cat'] == 'Probable/Definite']
    }
    
    print("\nAligned Category Pool Sizes (under 6000 tokens):")
    for cat, items in aligned_cats.items():
        print(f"  - {cat}: {len(items)}")
        
    # Selection logic targeting category balance:
    # 1. Take all available aligned Probable/Definite records first
    # 2. Take all available aligned Doubtful records next
    # 3. Fill the remaining target from aligned Possible records (prioritizing under 4k tokens)
    selected_aligned = []
    
    # Select Probable/Definite
    prob_def_aligned = aligned_cats['Probable/Definite']
    selected_aligned += prob_def_aligned
    print(f"\nSelecting all {len(prob_def_aligned)} aligned Probable/Definite cases.")
    
    # Select Doubtful
    doubtful_aligned = aligned_cats['Doubtful']
    selected_aligned += doubtful_aligned
    print(f"Selecting all {len(doubtful_aligned)} aligned Doubtful cases.")
    
    # Remaining needed
    remaining_aligned_needed = target_aligned - len(selected_aligned)
    print(f"Remaining aligned samples needed from Possible: {remaining_aligned_needed}")
    
    # Select from Possible aligned
    poss_aligned_pool = aligned_cats['Possible']
    poss_under_pref = [r for r in poss_aligned_pool if r['tokens'] <= args.pref_tokens]
    poss_above_pref = [r for r in poss_aligned_pool if r['tokens'] > args.pref_tokens]
    
    selected_poss = []
    if len(poss_under_pref) >= remaining_aligned_needed:
        selected_poss = random.sample(poss_under_pref, remaining_aligned_needed)
    else:
        selected_poss = list(poss_under_pref)
        needed = remaining_aligned_needed - len(selected_poss)
        selected_poss += random.sample(poss_above_pref, needed)
        
    selected_aligned += selected_poss
    print(f"Selected {len(selected_poss)} aligned Possible cases.")
    
    # Verify medical review counts
    selected_medical_pool = selected_mismatch + selected_aligned
    print(f"\nTotal selected medical reviews: {len(selected_medical_pool)}")
    
    # Count Naranjo categories in final selected medical reviews
    final_cats = {}
    for r in selected_medical_pool:
        cat = r['causality_cat']
        final_cats[cat] = final_cats.get(cat, 0) + 1
    print(f"Final medical reviews category distribution: {final_cats}")
    
    # 5. Generate Negatives (300 total, 100 of each, uniform schema)
    target_neg_size = 300
    print(f"\nGenerating {target_neg_size} synthetic negative controls...")
    negatives = generate_negative_cases(count_per_cat=target_neg_size // 3)
    selected_negatives = [n['sample'] for n in negatives]
    
    # Extract reviews
    selected_medical_reviews = [r['sample'] for r in selected_medical_pool]
    
    # 6. Combine and Shuffle
    final_dataset = selected_medical_reviews + selected_negatives
    random.shuffle(final_dataset)
    
    # 7. Save to V2 Dataset File
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f_out:
        for sample in final_dataset:
            f_out.write(json.dumps(sample, ensure_ascii=False) + '\n')
            
    # Calculate stats of the new dataset
    final_token_counts = [calculate_tokens(s, enc) for s in final_dataset]
    mean_len = np.mean(final_token_counts)
    max_len = np.max(final_token_counts)
    under_4k_count = sum(1 for c in final_token_counts if c <= args.pref_tokens)
    
    print("\n" + "="*50)
    print("COMPILATION SUMMARY - NEW V2 DATASET")
    print("="*50)
    print(f"Output File Path : {args.output}")
    print(f"Total Records    : {len(final_dataset)}")
    print(f"  - Medical reviews: {len(selected_medical_reviews)}")
    print(f"    - Aligned normal: {len(selected_aligned)}")
    print(f"    - Drug mismatches: {len(selected_mismatch)}")
    print(f"  - Negative reviews: {len(selected_negatives)}")
    print(f"Average Token Size: {mean_len:.2f} tokens")
    print(f"Max Token Size    : {max_len} tokens")
    print(f"Records <= {args.pref_tokens} : {under_4k_count} ({under_4k_count/len(final_dataset)*100:.2f}%)")
    print(f"Records > {args.pref_tokens}  : {len(final_dataset) - under_4k_count} ({(len(final_dataset) - under_4k_count)/len(final_dataset)*100:.2f}%)")
    print("="*50)

if __name__ == '__main__':
    main()
