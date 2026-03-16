from __future__ import annotations

"""Built-in LLM handler for workflow steps."""

from typing import Any, Dict, Optional

from .client import LLMClient
from ..state import RuntimeState
from ..utils import render_path_template


def make_llm_handler(client: LLMClient):
    """Return a handler bound to the provided LLM client.

    TODO: Support structured outputs (JSON schema) and response validation.
    TODO(testing): Add test_llm_handler.py with E2E tests that mock LLMClient
      and verify: prompt template rendering, response_key mapping, metadata
      inclusion, error propagation. This is the most critical untested path.
    TODO(example): Create a real-world example workflow (workflows/samples/05_llm_call.yaml)
      that uses `handler: llm` with a live OpenAI/Anthropic call to demonstrate
      the "first five minutes" experience for new users.
    """

    def _handler(state: RuntimeState, full_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = state.to_dict()
        llm_cfg = {}

        cfg_block = payload.get("__llm__")
        if isinstance(cfg_block, dict):
            llm_cfg.update(cfg_block)

        for key in (
            "prompt",
            "model",
            "system",
            "provider",
            "response_key",
            "temperature",
            "max_tokens",
            "params",
            "include_metadata",
        ):
            if key in payload and key not in llm_cfg:
                llm_cfg[key] = payload[key]

        prompt_template = llm_cfg.get("prompt")
        model = llm_cfg.get("model")
        if not isinstance(prompt_template, str) or not prompt_template.strip():
            raise ValueError("LLM handler requires a non-empty prompt string.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("LLM handler requires a non-empty model string.")

        full = full_state or payload
        # TODO: Support alternative template syntaxes (e.g., single-brace or format-style).
        prompt = render_path_template(prompt_template, full)

        system_template = llm_cfg.get("system")
        system = None
        if isinstance(system_template, str) and system_template.strip():
            system = render_path_template(system_template, full)

        params: Dict[str, Any] = {}
        if "temperature" in llm_cfg:
            params["temperature"] = llm_cfg.get("temperature")
        if "max_tokens" in llm_cfg:
            params["max_tokens"] = llm_cfg.get("max_tokens")
        if isinstance(llm_cfg.get("params"), dict):
            params.update(llm_cfg["params"])

        context = payload.get("__llm_context__")
        if not isinstance(context, dict):
            context = None

        response = client.call(
            model=model,
            prompt=prompt,
            provider=llm_cfg.get("provider"),
            system=system,
            params=params,
            context=context,
        )

        response_key = llm_cfg.get("response_key") or "text"
        output = {response_key: response.text}

        if llm_cfg.get("include_metadata"):
            output["llm"] = {
                "provider": response.provider,
                "model": response.model,
                "usage": response.usage,
            }

        return output

    return _handler
