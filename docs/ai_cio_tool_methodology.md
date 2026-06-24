# AI CIO Tool Methodology Registry

This registry documents what each AI CIO input tool is allowed to say, how its signal should be interpreted, and where the LLM must defer to deterministic adapter output.

The daily AI CIO prompt does not ingest this full document. It ingests compact methodology cards generated from this registry's principles, plus the daily structured metrics snapshot.

## Global Rules

- Adapter outputs are authoritative when available: `tool_score`, `tool_regime`, `tool_bias`, and `score_reason`.
- Human-readable child reports are supporting evidence, not the scoring source of truth.
- The LLM may explain a score or apply a controlled overlay, but it must not relabel a tool from raw prose when an adapter score exists.
- History is for persistence and deltas only. It must not anchor today's score.
- Missing metrics must be reported as `DATA INSUFFICIENT`; do not infer missing values from memory.

## Fed Liquidity

- Domain: global liquidity.
- Horizon: 4-12 weeks.
- Primary signal: net liquidity, liquidity impulse, and liquidity quality.
- Interpretation: organic liquidity support is constructive; emergency balance-sheet expansion can indicate system stress.
- Limit: not a standalone VNINDEX timing signal.

## Global Financial Conditions

- Domain: external credit and macro stress.
- Horizon: 4-12 weeks.
- Primary signal: CQS percentile and global stress components.
- Interpretation: high CQS percentile is a macro headwind.
- Limit: short-term news sentiment must not offset hard credit stress.

## US Margin Debt / M2 Overlay

- Domain: speculative leverage.
- Horizon: monthly and lagged.
- Primary signal: margin debt to M2 level, percentile, and z-score.
- Interpretation: high leverage amplifies downside when liquidity or breadth is weak.
- Limit: never a standalone hard regime switch.

## VNIBOR

- Domain: domestic funding liquidity.
- Horizon: 1-4 weeks.
- Primary signal: overnight rate plus 20-session stress trend.
- Interpretation: persistent tightening/liquidity squeeze is a risk headwind.
- Limit: one easy snapshot does not erase a stressed trend.

## LTMM

- Domain: liquidity transmission.
- Horizon: 1-8 weeks.
- Primary signal: upstream-to-downstream transmission state across FLI, MLI, TE, FRI bottlenecks, and FIRE / near-FIRE triggers.
- Interpretation: FLI is only upstream funding supply. If FLI is neutral/easy while MLI tightens, TE breaks down, or FRI bottlenecks fire, treat the system as transmission blockage rather than macro relief.
- Limit: not a standalone crash signal.
- AI CIO rule: never summarize LTMM by FLI alone; mention the dominant downstream bottleneck and trigger state when LTMM is material.

## VN100 Corporate Health

- Domain: bottom-up fundamental health.
- Horizon: quarterly.
- Primary signal: health score, growth breadth, cash-flow confirmation, working-capital stress, leverage stress.
- Interpretation: improves or weakens confidence in market-internal signals.
- Limit: not a short-term timing model and not a direct stock-picking instruction.

## Humility / Falsification Monitor

- Domain: thesis audit.
- Horizon: current data versus prior falsification rules.
- Primary signal: triggered rules and thesis status.
- Interpretation: WATCH/FALSIFIED must be discussed in trend, confidence, and allocation.
- Limit: it audits a prior thesis; it does not create a new thesis by itself.

## Fear & Greed

- Domain: sentiment and positioning.
- Horizon: days to weeks.
- Primary signal: risk score and sentiment regime.
- Interpretation: supportive when risk appetite is healthy, cautionary when extremes are unstable.
- Limit: secondary to liquidity, breadth, and tail-risk constraints.

## Manipulation / Coupling

- Domain: index concentration and coupling risk.
- Horizon: days to weeks.
- Primary signal: Vingroup slope percentile and concentration diagnostics.
- Interpretation: high concentration risk can make index-level signals fragile.
- Limit: mostly idiosyncratic/system-structure risk; do not overrule broad systemic tools alone.

## Dispersion

- Domain: market structure and participation quality.
- Horizon: days to weeks.
- Primary signal: dispersion pressure and correlation behavior.
- Interpretation: helps distinguish broad participation from narrow index movement.
- Limit: low dispersion can mean compressed/idle risk, not automatically bullish.

## Upside Ratio

- Domain: upside participation.
- Horizon: days to weeks.
- Primary signal: upside participation ratio and breadth confirmation.
- Interpretation: sustained upside participation supports risk-on.
- Limit: zombie rallies without breadth confirmation should not lift regime materially.

## Bank Valuation

- Domain: sector valuation.
- Horizon: weeks to months.
- Primary signal: valuation gap, quality flags, and market confirmation.
- Interpretation: helps identify banks that are fair/undervalued with acceptable quality.
- Limit: cheap banks are not buy signals when the AI CIO allocation regime forbids equity risk.

## Market Breadth

- Domain: market-internal participation.
- Horizon: days to weeks.
- Primary signal: breadth MA20 and moving-average participation.
- Interpretation: weak breadth caps bullish conclusions.
- Limit: breadth is powerful but still interacts with liquidity and tail-risk.

## ESR Monitor

- Domain: systemic stress.
- Horizon: days to weeks.
- Primary signal: Systemic Stress Index (SSI) and market state.
- Interpretation: high SSI activates tail-risk caution.
- Limit: valuation support must not soften systemic stress by itself.

## VaRES

- Domain: contagion and complacency.
- Horizon: days to weeks.
- Primary signal: contagion, crash-risk, and complacency modules.
- Interpretation: useful for tail-risk color and avoid lists.
- Limit: not a standalone composite score unless an adapter provides one.

## Var-CVaR VNINDEX

- Domain: left-tail risk.
- Horizon: days to weeks.
- Primary signal: EVT tail index xi, VaR, CVaR, and expected shortfall.
- Interpretation: high xi is a hard warning even when realized volatility is quiet.
- Limit: do not offset high xi with sentiment alone.

## Sentiment Factor From News

- Domain: news sentiment.
- Horizon: 1-3 days.
- Primary signal: news sentiment factor and narrative tone.
- Interpretation: useful for near-term noise and tactical color.
- Limit: cannot veto macro, funding, breadth, or tail-risk stress.

## Risk-Adjusted Growth

- Domain: bank growth quality.
- Horizon: weeks to months.
- Primary signal: economic alpha, ROE stability, payout quality.
- Interpretation: used with Bank Valuation for bank selection.
- Limit: cannot override low market allocation regimes.

## PVGO Valuation

- Domain: valuation expectation risk.
- Horizon: medium term.
- Primary signal: PVGO percentage, P/E, and cost-of-equity assumption.
- Interpretation: elevated PVGO means the market is pricing higher embedded future growth expectations.
- Limit: PVGO is not a crash timing signal. It amplifies risk when breadth, liquidity, or tail risk are already weak.
- Authority: the PVGO adapter score/regime/bias are authoritative; the LLM must not relabel from raw PVGO percentage.

## ABM Market Simulator

- Domain: ABM v4 pre-shock early-warning and margin cascade stress.
- Horizon: days to weeks.
- Primary signal: early-warning score and early-warning level.
- Interpretation: YELLOW, ORANGE, and RED reduce risk budget before a shock; distance to cascade, panic ratio, average leverage, and cascade vulnerability are supporting diagnostics.
- Limit: ABM is a pre-shock stress diagnostic, not an exact crash-timing model or standalone buy/sell signal.
- Authority: ABM v4 early-warning score/level and the adapter score/regime/bias are authoritative when CSV metrics are available.
