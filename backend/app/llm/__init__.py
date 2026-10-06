"""The only door to a language model (CLAUDE.md rule 5).

Every LLM call goes through `complete_structured()` in client.py: LiteLLM sends it to
whichever model the settings name (Ollama locally, a hosted model later), the answer is
validated against a Pydantic schema, a wrong answer gets one repair retry, and a second
failure raises LlmError. No provider SDK is imported anywhere else.
"""
