---
license: apache-2.0
datasets:
- arampacha/rsicd
metrics:
- bleu
library_name: transformers
pipeline_tag: image-to-text
---

# BLIP for RSICD image captioning:

- [`blip-image-captioning-base`](https://huggingface.co/Salesforce/blip-image-captioning-base/) model has been finetuned on the [`rsicd`](https://huggingface.co/datasets/arampacha/rsicd) dataset. Training parameters used are as follows:
  - **learning_rate** = 5e-7
  - **optimizer** = AdamW
  - **scheduler** = ReduceLROnPlateau
  - **epochs** = 5
- More details (demo, testing, evaluation, metrics) available at [`github repo`](https://github.com/gurveervirk/TRINIT-Prometheans-ML03?tab=readme-ov-file)