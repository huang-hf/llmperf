import json
import os
import time
from typing import Any, Dict

import ray
import requests

from llmperf.ray_llm_client import LLMClient
from llmperf.models import RequestConfig
from llmperf import common_metrics
from llmperf.token_counter import count_tokens


# @ray.remote
class OpenAIChatCompletionsClient(LLMClient):
    """Client for OpenAI Chat Completions API."""

    def llm_request(self, request_config: RequestConfig) -> Dict[str, Any]:
        prompt = request_config.prompt
        prompt, prompt_len = prompt

        message = [
            {"role": "system", "content": ""},
            {"role": "user", "content": prompt},
        ]
        model = request_config.model
        body = {
            "model": model,
            "messages": message,
            "stream": True,
        }

        if request_config.provider is not None:
            body["provider"] = request_config.provider

        sampling_params = request_config.sampling_params
        body.update(sampling_params or {})
        time_to_next_token = []
        tokens_received = 0
        ttft = 0
        error_response_code = -1
        generated_text = ""
        error_msg = ""
        output_throughput = 0
        total_request_time = 0

        metrics = {}

        metrics[common_metrics.ERROR_CODE] = None
        metrics[common_metrics.ERROR_MSG] = ""

        start_time = time.monotonic()
        most_recent_received_token_time = time.monotonic()
        address = os.environ.get("OPENAI_API_BASE", "https://api.netmind.ai/inference-api/openai/v1")
        if not address:
            raise ValueError("the environment variable OPENAI_API_BASE must be set.")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("the environment variable OPENAI_API_KEY must be set.")
        headers = {"Authorization": f"Bearer {key}"}
        if not address:
            raise ValueError("No host provided.")
        if not address.endswith("/"):
            address = address + "/"
        address += "chat/completions"
        print("body: ", body)
        try:
            with requests.post(
                address,
                json=body,
                stream=True,
                timeout=1800,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    error_msg = response.text
                    print("error_msg: ", error_msg)
                    error_response_code = response.status_code
                    response.raise_for_status()
                for chunk in response.iter_lines(chunk_size=None):
                    chunk = chunk.strip()

                    if not chunk:
                        continue
                    stem = "data: "
                    chunk = chunk[len(stem) :]
                    if chunk == b"[DONE]":
                        continue
                    try:
                        data = json.loads(chunk)
                    except Exception as e:
                        print("not json format chunk: ", chunk)
                        continue

                    if "error" in data:
                        error_msg = data["error"]["message"]
                        error_response_code = data["error"]["code"]
                        raise RuntimeError(data["error"]["message"])

                    delta = data["choices"][0]["delta"]
                    content = delta.get("content", None)
                    if not content:
                        content = delta.get("reasoning_content", None)
                    if content:
                        if not ttft:
                            ttft = time.monotonic() - start_time
                            time_to_next_token.append(ttft)
                        else:
                            time_to_next_token.append(time.monotonic() - most_recent_received_token_time)
                        most_recent_received_token_time = time.monotonic()
                        generated_text += content

            total_request_time = time.monotonic() - start_time
            tokens_received = count_tokens([{"role": "assistant", "content": generated_text}])
            output_throughput = tokens_received / total_request_time

        except Exception as e:
            metrics[common_metrics.ERROR_MSG] = error_msg
            metrics[common_metrics.ERROR_CODE] = error_response_code
            import traceback

            stack_trace = traceback.format_exc()
            print(f"Warning Or Error: {stack_trace}")
            print(error_response_code)

        if len(time_to_next_token) == 0:
            print("Warning: No tokens received.")
            return

        # metrics[common_metrics.INTER_TOKEN_LAT] = sum(time_to_next_token) #This should be same as metrics[common_metrics.E2E_LAT]. Leave it here for now
        metrics[common_metrics.INTER_TOKEN_LAT] = sum(time_to_next_token) / len(time_to_next_token)
        metrics[common_metrics.TTFT] = ttft
        metrics[common_metrics.E2E_LAT] = total_request_time
        metrics[common_metrics.REQ_OUTPUT_THROUGHPUT] = output_throughput
        metrics[common_metrics.NUM_TOTAL_TOKENS] = tokens_received + prompt_len
        metrics[common_metrics.NUM_OUTPUT_TOKENS] = tokens_received
        metrics[common_metrics.NUM_INPUT_TOKENS] = prompt_len

        return metrics, generated_text, request_config
