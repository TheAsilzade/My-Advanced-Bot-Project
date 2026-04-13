import logging
from typing import Awaitable, Callable, List, Optional, TYPE_CHECKING

from google.genai import types

if TYPE_CHECKING:
    from google import genai

logger = logging.getLogger(__name__)

ToolCallback = Callable[[types.FunctionCall], Awaitable[types.Part]]


class ResponseGenerator:
    """Generate Gemini responses and handle tool calls."""

    def __init__(
        self,
        client: "genai.Client",
        model_name: str,
        tools: List[types.Tool],
        system_instruction: str,
        temperature: float = 0.7,
        *,
        top_p: Optional[float] = 0.9,
        thinking_budget: int = 4096,
    ):
        self._client = client
        self._model_name = model_name
        self._tools = tools
        self._system_instruction = system_instruction
        self._temperature = temperature
        self._top_p = top_p
        self._thinking_budget = thinking_budget

    def build_generation_config(self) -> types.GenerateContentConfig:

        return types.GenerateContentConfig(
            tools=self._tools,
            thinking_config=types.ThinkingConfig(
                thinking_budget=self._thinking_budget
            ),
            system_instruction=self._system_instruction,
            temperature=self._temperature,
            top_p=self._top_p,
        )

    async def generate_reply(
        self,
        history: List[types.Content],
        tool_callback: ToolCallback,
    ) -> Optional[str]:

        config = self.build_generation_config()

        try:

            response = await self._client.aio.models.generate_content(
                model=self._model_name,
                contents=history,
                config=config,
            )

        except Exception as exc:

            logger.error("Gemini request failed: %s", exc)

            # rate limit veya network hatası
            if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                return "I'm thinking too fast and hit my limit 😵‍💫 Please try again in a moment."

            return "Something went wrong while thinking."

        if not response.candidates:
            return None

        candidate = response.candidates[0]
        content = candidate.content

        if not content:
            return None

        history.append(content)

        final_text = ""
        tool_calls = 0

        for part in content.parts:

            if part.function_call:

                if tool_calls >= 2:
                    continue

                tool_calls += 1

                feedback = await tool_callback(part.function_call)

                history.append(
                    types.Content(
                        role="user",
                        parts=[feedback],
                    )
                )

            elif part.text:
                final_text = part.text

        return final_text.strip() or None