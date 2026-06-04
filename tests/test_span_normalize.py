import unittest

from kyoko.span_normalize import normalize_span


class SpanNormalizeTests(unittest.TestCase):
    def test_ai_sdk_llm(self) -> None:
        result = normalize_span(
            name="generate",
            attributes={
                "ai.prompt.messages": '[{"role":"user","content":"hi"}]',
                "gen_ai.request.model": "gpt-x",
                "gen_ai.usage.input_tokens": 10,
            },
        )
        self.assertEqual(result["kind"], "llm")
        self.assertEqual(result["model"], "gpt-x")
        self.assertIsInstance(result["messages"], list)
        self.assertEqual(result["messages"][0]["content"], "hi")

    def test_gen_ai_tool(self) -> None:
        result = normalize_span(
            name="search",
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "search",
            },
        )
        self.assertEqual(result["kind"], "tool")
        self.assertEqual(result["tool_name"], "search")

    def test_generic_gen_ai_llm(self) -> None:
        result = normalize_span(
            name="invoke",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.request.model": "m",
            },
        )
        self.assertEqual(result["kind"], "llm")

    def test_unknown_attributes_fall_back(self) -> None:
        result = normalize_span(name="mystery", attributes={"foo": "bar"})
        self.assertEqual(result["kind"], "other")
        self.assertEqual(result["adapter"], "fallback")

    def test_every_result_has_adapter_and_valid_kind(self) -> None:
        cases = [
            {"ai.prompt.messages": '[{"role":"user","content":"hi"}]'},
            {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "search"},
            {"gen_ai.operation.name": "invoke_agent", "gen_ai.request.model": "m"},
            {"foo": "bar"},
        ]
        for attributes in cases:
            with self.subTest(attributes=attributes):
                result = normalize_span(name="x", attributes=attributes)
                self.assertIsInstance(result["adapter"], str)
                self.assertIn(result["kind"], {"llm", "tool", "other"})


if __name__ == "__main__":
    unittest.main()
