import os
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "9.4.2"
# os.environ["HF_HUB_DISABLE_DISK_SPACE_WARNING"] = "1"

from unsloth import FastLanguageModel
import torch
max_seq_length = 8192 # Choose any! We auto support RoPE Scaling internally!
dtype = None # None for auto detection. Float16 for Tesla T4, V100, Bfloat16 for Ampere+
load_in_4bit = True # Use 4bit quantization to reduce memory usage. Can be False.

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Llama-3.3-70B-Instruct", # or choose "unsloth/Llama-3.2-1B-Instruct"
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
    # token = "YOUR_HF_TOKEN", # HF Token for gated models
)

model = FastLanguageModel.get_peft_model(
    model,
    r = 64, # Choose any number > 0 ! Suggested 8, 16, 32, 64, 128
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                      "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 128,
    lora_dropout = 0, # Supports any, but = 0 is optimized
    bias = "none",    # Supports any, but = "none" is optimized
    # [NEW] "unsloth" uses 30% less VRAM, fits 2x larger batch sizes!
    use_gradient_checkpointing = "unsloth", # True or "unsloth" for very long context
    random_state = 3407,
    use_rslora = False,  # We support rank stabilized LoRA
    loftq_config = None, # And LoftQ
)

from datasets import Dataset
import json

# Load local PV dataset (already in {'role','content'} ChatML format)
def load_pv_dataset(path):
    records = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return Dataset.from_list(records)

# 1. Load the full dataset from dataset/
full_dataset = load_pv_dataset("dataset/pv_safety_review_dataset_3000.jsonl")

# 2. Shuffle and split 90:10 (using a fixed seed for reproducibility)
# This results in 2700 training samples and 300 test/evaluation samples.
split_dataset = full_dataset.train_test_split(test_size=0.1, seed=3407, shuffle=True)
dataset = split_dataset["train"]       # 90% split for training
test_dataset = split_dataset["test"]   # 10% split for post-training testing

# 3. Save the test split to /dataset/ so you can easily load/use it later
test_dataset.to_json("dataset/pv_test_split_300.jsonl")
print(f"Dataset successfully split: {len(dataset)} train samples, {len(test_dataset)} test samples.")
print("Saved 10% test split to 'dataset/pv_test_split_300.jsonl' for post-training evaluation.")

# Serialize messages to text using the model's built-in Llama 3.3 chat template
def formatting_prompts_func(examples):
    convos = examples["messages"]
    texts = [tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False) for convo in convos]
    return {"text": texts}

# Apply formatting only to the training dataset
dataset = dataset.map(formatting_prompts_func, batched=True)

from trl import SFTConfig, SFTTrainer
from transformers import DataCollatorForSeq2Seq

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    # data_collator = DataCollatorForSeq2Seq(tokenizer = tokenizer),
    packing = False, # Can make training 5x faster for short sequences.
    args = SFTConfig(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 8,
        # warmup_steps = 5,
        warmup_ratio = 0.05,
        num_train_epochs = 2, # Set this for 1 full training run.
        learning_rate = 2e-5,
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.001,
        lr_scheduler_type = "cosine",
        seed = 3407,
        output_dir = "outputs",
        report_to = "none", # Use TrackIO/WandB etc,
        bf16 = True,

        # --- NEW STEP-WISE SAVING LOGIC ---
        save_strategy = "steps", # Changed from "epoch"
        save_steps = 20,         # Saves a new checkpoint every 20 steps
        save_total_limit = 3,    # Only keeps the 3 most recent checkpoints to save disk space
        # ----------------------------------
    ),
)

from unsloth.chat_templates import train_on_responses_only
trainer = train_on_responses_only(
    trainer,
    instruction_part = "<|start_header_id|>user<|end_header_id|>\n\n",
    response_part = "<|start_header_id|>assistant<|end_header_id|>\n\n",
)

# trainer_stats = trainer.train()
resume_checkpoint = True if os.path.exists("outputs") and any("checkpoint" in d for d in os.listdir("outputs")) else False

trainer_stats = trainer.train(resume_from_checkpoint=resume_checkpoint)

model.save_pretrained("MedFT_Llama3_3_70B_16bit_adapters")  # Local saving
tokenizer.save_pretrained("MedFT_Llama3_3_70B_16bit_adapters")
model.push_to_hub("AnishV004/MedFT_Llama3_3_70B_16bit_adapters", token = "") # Online saving
tokenizer.push_to_hub("AnishV004/MedFT_Llama3_3_70B_16bit_adapters", token = "") # Online saving

