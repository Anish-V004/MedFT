import os
import json
import random
import re
import argparse
import sys
import pandas as pd

# Ensure UTF-8 printing on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Constants
SYSTEM_PROMPT = (
    "You are a Pharmacovigilance (PV) Medical Review Assistant. "
    "CRITICAL GROUNDING RULE: You must base your entire evaluation STRICTLY and EXCLUSIVELY on the provided Patient Narrative. "
    "Do NOT invent, hallucinate, or bring in external patient cases. Do NOT reference drugs or adverse events that are not explicitly written in the user's prompt. "
    "If the provided RSI does not match the drug in the narrative, explicitly state 'Drug Mismatch - Cannot Evaluate' in your reasoning."
)

# Admin Noise Templates
ADMIN_NOISE_TEMPLATES = [
    "Consumer called to ask for a refund for their prescription of {drug}. The package was damaged during shipping.",
    "Medical records were requested for the patient taking {drug} but they have not been provided by the clinical site.",
    "Follow-up report for patient on {drug}: No new clinical information has been received at this time.",
    "Product quality complaint: The customer noticed a discolored tablet in the bottle of {drug}. No adverse events reported.",
    "Customer called to request a replacement bottle of {drug} because they misplaced their current medication.",
    "Administrative notice: The patient on {drug} requested to be removed from the pharmacy mailing list.",
    "Insurance billing inquiry: Customer called to check co-pay pricing details for {drug}."
]

def parse_valid_review(sample):
    """Parses a valid ChatML review to extract its metrics for balancing."""
    messages = sample.get('messages', [])
    if len(messages) < 3:
        return None
        
    user_content = messages[1].get('content', '')
    assistant_content = messages[2].get('content', '')
    
    # Identify source
    source = 'openfda' if 'The suspected drug is' in user_content and 'experienced the following adverse events' in user_content else 'biodex'
    
    # Extract JSON block
    start_idx = assistant_content.find('{')
    end_idx = assistant_content.rfind('}')
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None
        
    try:
        json_data = json.loads(assistant_content[start_idx:end_idx+1])
        expectedness = json_data.get('expectedness', 'Unexpected')
        causality = json_data.get('causality', {})
        interpretation = causality.get('interpretation', 'Possible')
        naranjo = causality.get('naranjo_score', 1)
        
        # Categorize Naranjo
        if naranjo <= 0:
            causality_cat = 'Doubtful'
        elif 1 <= naranjo <= 4:
            causality_cat = 'Possible'
        else:
            causality_cat = 'Probable/Definite'
            
        return {
            'sample': sample,
            'source': source,
            'expectedness': expectedness,
            'causality_cat': causality_cat
        }
    except Exception:
        return None

def generate_negative_cases(count_per_cat=100):
    """Programmatically generates diversified negative escalation samples."""
    samples = []
    
    # Load raw datasets to grab realistic demographics, reactions, and drugs
    fda_drugs = ["Lisinopril", "Aspirin", "Humira", "Atorvastatin", "Metoprolol", "Furosemide", "Soliris", "Amlodipine"]
    fda_reactions = ["Myocardial infarction", "Renal failure acute", "Thrombocytopenia", "Cardiac arrest", "Angina pectoris"]
    
    # Try to load real ones if files exist to make them highly clinical
    if os.path.exists('data/fda_cardio_clinical.csv'):
        try:
            df = pd.read_csv('data/fda_cardio_clinical.csv', nrows=100)
            if not df.empty:
                fda_drugs = [d.split(';')[0].strip() for d in df['drugs'].dropna() if d]
                fda_reactions = [r.split(';')[0].strip() for r in df['reactions'].dropna() if r]
        except Exception:
            pass
            
    # 1. Missing Drugs (100 samples)
    for i in range(count_per_cat):
        age = random.randint(18, 85)
        sex = random.choice(["male", "female"])
        reaction = random.choice(fda_reactions)
        
        narrative = f"A {age} year-old {sex} patient experienced the following adverse events: {reaction}. The suspect medication was not documented in the safety report."
        rsi_text = "RSI not available"
        
        assistant_json = {
            "chain_of_thought": "Evaluation failed: The patient narrative does not mention any suspect medication. A clinical pharmacovigilance review cannot be performed without identifying the administered drug.",
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
        assistant_content = f"{assistant_json['chain_of_thought']}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
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

    # 2. Missing Events (100 samples)
    for i in range(count_per_cat):
        age = random.randint(18, 85)
        sex = random.choice(["male", "female"])
        drug = random.choice(fda_drugs)
        
        narrative = f"A {age} year-old {sex} patient was prescribed {drug} for cardiovascular therapy. No adverse events, complaints, or physical symptoms were reported during the follow-up period."
        rsi_text = f"BOXED WARNING:\nWARNING: Serious events are possible.\n\nWARNINGS AND CAUTIONS:\nMonitor patient closely.\n\nADVERSE REACTIONS:\nHeadache, nausea."
        
        assistant_json = {
            "chain_of_thought": "Evaluation failed: The patient narrative does not describe any adverse events or reactions. A safety assessment cannot be completed without a reported reaction.",
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
        assistant_content = f"{assistant_json['chain_of_thought']}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
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

    # 3. Administrative Noise (100 samples)
    for i in range(count_per_cat):
        drug = random.choice(fda_drugs)
        template = random.choice(ADMIN_NOISE_TEMPLATES)
        narrative = template.format(drug=drug)
        rsi_text = "RSI not available"
        
        assistant_json = {
            "chain_of_thought": f"Evaluation failed: The text contains only administrative or clerical metadata ('{narrative.split('.')[0].lower()}') and does not describe a clinical patient case. No safety review can be concluded.",
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
        assistant_content = f"{assistant_json['chain_of_thought']}\n\n```json\n{json.dumps(assistant_json, indent=2)}\n```"
        
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
    parser = argparse.ArgumentParser(description=" Diversified Golden Subset Dataset Balancer & Compiler.")
    parser.add_argument('--preview', action='store_true',
                        help="If set, outputs exactly one sample from each of the 6 categories for user review.")
    parser.add_argument('--output', type=str, default='data/golden_train_3000.jsonl',
                        help="Path to save the compiled dataset.")
    parser.add_argument('--size', type=int, default=3000,
                        help="Total size of the Golden Subset (default 3000).")
    parser.add_argument('--neg-size', type=int, default=300,
                        help="Total negative escalation samples to include (default 300).")
    args = parser.parse_args()
    
    print("==================================================")
    print("PHARMACOVIGILANCE DIVERSIFIED DATASET COMPILER")
    print("==================================================")
    
    # 1. Load existing valid reviews
    valid_pool = []
    for fpath in ['data/biodex_chatml.jsonl', 'data/fda_chatml.jsonl']:
        if os.path.exists(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        parsed = parse_valid_review(json.loads(line))
                        if parsed:
                            valid_pool.append(parsed)
                            
    print(f"Loaded {len(valid_pool)} successfully generated valid reviews from pool.")
    
    # Categorize valid reviews for balancing
    categories = {
        'Doubtful': [r for r in valid_pool if r['causality_cat'] == 'Doubtful'],
        'Possible': [r for r in valid_pool if r['causality_cat'] == 'Possible'],
        'Probable/Definite': [r for r in valid_pool if r['causality_cat'] == 'Probable/Definite']
    }
    
    # 2. Preview Mode
    if args.preview:
        print("\n" + "="*70)
        print("                 PREVIEW: 6-CATEGORY DATASET FORMAT")
        print("="*70)
        
        # Display 1 from each valid category
        for cat_name, items in categories.items():
            print(f"\n--- [CATEGORY: Valid Medical Case - {cat_name}] ---")
            if items:
                sample = items[0]['sample']
                print(f"User narrative: {sample['messages'][1]['content'][:300]}...")
                print(f"Assistant response:\n{sample['messages'][2]['content']}")
            else:
                print("  (No valid reviews generated yet in this category. Generate pool first.)")
            print("-"*70)
            
        # Generate and display 1 from each negative category
        negatives = generate_negative_cases(count_per_cat=1)
        for neg in negatives:
            print(f"\n--- [CATEGORY: Negative Escalation Case - {neg['category']}] ---")
            sample = neg['sample']
            print(f"User narrative: {sample['messages'][1]['content']}")
            print(f"Assistant response:\n{sample['messages'][2]['content']}")
            print("-"*70)
            
        # Write previews to a file
        preview_path = 'data/category_previews.jsonl'
        with open(preview_path, 'w', encoding='utf-8') as f_out:
            for cat_name, items in categories.items():
                if items:
                    f_out.write(json.dumps(items[0]['sample'], ensure_ascii=False) + '\n')
            for neg in negatives:
                f_out.write(json.dumps(neg['sample'], ensure_ascii=False) + '\n')
                
        print(f"\nSaved preview samples to '{preview_path}'")
        return

    # 3. Full Balancing & Compilation Mode
    target_valid_size = args.size - args.neg_size
    print(f"\nTarget Split:\n  - Valid Medical Reviews: {target_valid_size} rows\n  - Negative Escalation:   {args.neg_size} rows")
    
    if len(valid_pool) < target_valid_size:
        print(f"\nWARNING: Only {len(valid_pool)} valid reviews generated in pool. Need {target_valid_size}.")
        print("To build a perfectly balanced dataset of this size, run generate_reviews.py --full-run first.")
        print("We will compile all available valid reviews and generate the negative rows.")
        selected_valid = [r['sample'] for r in valid_pool]
    else:
        # Perform combinatorial sampling to achieve balance
        # target counts per causality category
        per_cat_target = target_valid_size // 3
        
        selected_valid = []
        for cat_name, items in categories.items():
            if len(items) >= per_cat_target:
                # Sample evenly from Expected/Unexpected if possible
                expected = [x for x in items if x['expectedness'] == 'Expected']
                unexpected = [x for x in items if x['expectedness'] == 'Unexpected']
                
                half_target = per_cat_target // 2
                
                sampled_exp = random.sample(expected, min(len(expected), half_target))
                sampled_unexp = random.sample(unexpected, min(len(unexpected), per_cat_target - len(sampled_exp)))
                
                sampled_items = sampled_exp + sampled_unexp
                # Fallback to general sample if needed to hit target
                if len(sampled_items) < per_cat_target:
                    remaining = [x for x in items if x not in sampled_items]
                    sampled_items += random.sample(remaining, per_cat_target - len(sampled_items))
                
                selected_valid += [x['sample'] for x in sampled_items]
            else:
                # Take all we have
                selected_valid += [x['sample'] for x in items]
                
        # Fill in up to target_valid_size if any category was short
        if len(selected_valid) < target_valid_size:
            remaining = [r['sample'] for r in valid_pool if r['sample'] not in selected_valid]
            selected_valid += random.sample(remaining, min(len(remaining), target_valid_size - len(selected_valid)))

    # Generate 300 negative cases (100 per category)
    neg_count_per_cat = args.neg_size // 3
    negatives = generate_negative_cases(count_per_cat=neg_count_per_cat)
    selected_negatives = [n['sample'] for n in negatives]
    
    # Combine and shuffle
    final_dataset = selected_valid + selected_negatives
    random.shuffle(final_dataset)
    
    # Write to final jsonl
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f_out:
        for sample in final_dataset:
            f_out.write(json.dumps(sample, ensure_ascii=False) + '\n')
            
    print(f"\nCompilation successful! Saved {len(final_dataset)} records to '{args.output}'")
    print(f"  - Valid reviews: {len(selected_valid)}")
    print(f"  - Negative reviews: {len(selected_negatives)} ({neg_count_per_cat} of each category)")

if __name__ == '__main__':
    main()
