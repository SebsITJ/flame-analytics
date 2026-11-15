"""Output schema of the AI interpret step (v7). Pydantic -> JSON Schema -> Gemini response_json_schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Phase = Literal["prevent", "detect", "extinguish", "general"]
ClaimKind = Literal["observed", "computed", "extrapolation"]
ChartType = Literal["bar", "scatter", "strip"]
# Columns a chart may use: exactly the columns of the tables the tools return (flame/tools.TABLE_COLUMNS),
# minus row_id, plus "diluente" from compare_diluents.
ChartField = Literal["oxigeno", "presion", "combustible", "experimento", "fase",
                     "extinguished", "flame_recorded", "did_not_ignite", "metric_value", "diluente"]
CHART_TYPES = ("bar", "scatter", "strip")
CHART_FIELDS = ("oxigeno", "presion", "combustible", "experimento", "fase",
                "extinguished", "flame_recorded", "did_not_ignite", "metric_value", "diluente")


class Claim(BaseModel):
    text: str = Field(description="One short statement in the language of the question, with [R#]/[E#] citations.")
    phase: Phase
    kind: ClaimKind = Field(description="observed = written in a row; computed = an E# fact from a tool; "
                                        "extrapolation = beyond the tested conditions (the text must say so).")
    row_ids: list[str] = Field(default_factory=list, description="Row ids (R#) from the evidence pack.")
    evidence_ids: list[str] = Field(default_factory=list, description="Fact ids (E#) from the evidence pack.")


AgentName = Literal["prevention", "detection", "extinction", "timing"]
AGENT_NAMES = ("prevention", "detection", "extinction", "timing")


class AgentFinding(BaseModel):
    agent: AgentName = Field(description="One of the active_agents of the pack.")
    finding: str = Field(description="1-2 sentences: what this agent's own facts and rows show, with [R#]/[E#].")


class ChartSpec(BaseModel):
    type: ChartType
    evidence_id: str = Field(description="E# whose table is drawn. Never send data values.")
    x: ChartField
    y: ChartField
    color: ChartField | None = None
    title: str = Field(description="Short title in the language of the question.")


class InterpretedAnswer(BaseModel):
    enough_evidence: bool
    summary: str = Field(description="What the evidence shows, in 2-4 sentences with [R#]/[E#] citations.")
    conclusion: str = Field(default="", description="Direct verdict on the question in 2-4 sentences: is the "
                            "scenario supported, contradicted or not covered by the experiments, with the governing "
                            "numbers copied from the pack and [R#]/[E#] citations.")
    recommendation: str = Field(default="", description="1-3 sentences: what the evidence in the pack supports "
                                "doing, with [R#]/[E#] citations. Only from the pack, never outside knowledge.")
    agents: list[AgentFinding] = Field(default_factory=list, description="One finding per active agent.")
    claims: list[Claim] = Field(default_factory=list, description="At most 8 claims.")
    chart: ChartSpec | None = None
    limitations: str = ""
    missing: str = Field(default="", description="Data that would be needed; empty if nothing is missing.")


def response_schema() -> dict:
    """JSON Schema sent to Gemini. conclusion and recommendation are optional in the Pydantic model (older
    answers and tests stay valid) but the model is asked to always write them."""
    schema = InterpretedAnswer.model_json_schema()
    required = list(schema.get("required", []))
    for name in ("conclusion", "recommendation", "agents"):
        if name not in required:
            required.append(name)
    schema["required"] = required
    return schema
