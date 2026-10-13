"""The only door to a language model (CLAUDE.md rule 5).

Every LLM call goes through `complete_structured()` in client.py: LiteLLM sends it to
whichever model the settings name (Ollama locally, a hosted model later), the answer is
validated against a Pydantic schema, a wrong answer gets one repair retry, and a second
failure raises LlmError. No provider SDK is imported anywhere else. Embeddings (policy
search) have their own function, embed_texts() in embeddings.py, with the same rules.
"""

import os

# LiteLLM downloads a model price list from the internet when imported, unless told to use
# its bundled copy. Keep the app offline-capable and private. Set here, so it holds before any
# module of this package (chat answers, embeddings, tracing) imports LiteLLM.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
