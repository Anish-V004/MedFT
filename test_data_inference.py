import json
import os
import time
import torch

# 1. File Configuration
input_path = "dataset/pv_test_split_300.jsonl"
output_path = "dataset/pv_test_results_300.jsonl"

if True:
    from unsloth import FastLanguageModel
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = "AnishV004/MedFT_Llama3_3_70B_V2", # YOUR MODEL YOU USED FOR TRAINING
        max_seq_length = 8192,
        dtype = None,
        load_in_4bit = False,
    )
    FastLanguageModel.for_inference(model) # Enable native 2x faster inference


# Load the test dataset rows
test_samples = []
if os.path.exists(input_path):
    with open(input_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                test_samples.append(json.loads(line))
else:
    raise FileNotFoundError(f"Could not find the test file at {input_path}")

total_samples = len(test_samples)
print(f"Loaded {total_samples} test samples in sharegpt/chat format. Starting generation...\n")

start_time = time.time()

# 2. Iterate and process each sample sequentially
with open(output_path, "w", encoding="utf-8") as out_file:
    for idx, sample in enumerate(test_samples):
        # Extract the original message structure cleanly
        convo_messages = sample["messages"]
        inference_messages = [msg for msg in convo_messages if msg["role"] in ["system", "user"]]
        
        # Tokenize the prompt
        inputs = tokenizer.apply_chat_template(
            inference_messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt"
        ).to("cuda")
        
        # 3. Generate response
        with torch.inference_mode():
            outputs = model.generate(
                input_ids=inputs,
                max_new_tokens=512,
                use_cache=True,
                do_sample=True,      
                temperature=0.1,
                min_p=0.1,
                pad_token_id=tokenizer.pad_token_id
            )
        
        # Decode only the newly generated text slice
        input_length = inputs.shape[1]
        generated_tokens = outputs[0][input_length:]
        model_response = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
        
        # 4. Reconstruct the EXACT conversational tree structure
        # We append a 4th item (index 3) containing the new model's evaluation
        structured_messages = [
            {"role": "system", "content": next((msg["content"] for msg in convo_messages if msg["role"] == "system"), "")},
            {"role": "user", "content": next((msg["content"] for msg in convo_messages if msg["role"] == "user"), "")},
            {"role": "assistant", "content": next((msg["content"] for msg in convo_messages if msg["role"] == "assistant"), "")},
            {"role": "trained_model_response", "content": model_response} # Added as the 4th item
        ]
        
        # Save matching your original JSON tree structure
        output_record = {"messages": structured_messages}
        
        # Write line by line to disk
        out_file.write(json.dumps(output_record, ensure_ascii=False) + "\n")
        
        # Progress tracking indicator
        if (idx + 1) % 10 == 0 or (idx + 1) == total_samples:
            elapsed = time.time() - start_time
            avg_time = elapsed / (idx + 1)
            remaining_est = avg_time * (total_samples - (idx + 1))
            print(f"Processed: {idx + 1}/{total_samples} | "
                  f"Avg speed: {avg_time:.2f}s/sample | "
                  f"Est. Remaining: {remaining_est/60:.1f} mins")

end_time = time.time()
print(f"\nBatch processing complete! Output saved identically to original format in: {output_path}")