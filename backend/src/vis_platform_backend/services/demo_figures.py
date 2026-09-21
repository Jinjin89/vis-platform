from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from html import escape


class DemoFigureKind(StrEnum):
    SURVIVAL = "survival"
    DISTRIBUTION = "distribution"
    RELATIONSHIP = "relationship"
    GROUP_COMPARISON = "group_comparison"


@dataclass(frozen=True, slots=True)
class DemoFigure:
    """A deterministic, explicitly illustrative figure for the prototype workspace."""

    kind: DemoFigureKind
    title: str
    description: str
    svg: str


_SURVIVAL_TERMS = (
    "survival",
    "kaplan meier",
    "time to event",
    "time until event",
    "censoring",
    "mortality curve",
)
_DISTRIBUTION_TERMS = (
    "violin",
    "distribution",
    "density",
    "expression",
    "box plot",
    "boxplot",
    "transcript abundance",
)
_RELATIONSHIP_TERMS = (
    "scatter",
    "dose response",
    "correlation",
    "relationship",
    "association",
    "regression",
    "versus",
)


def classify_demo_figure(request_text: str) -> DemoFigureKind:
    """Choose a recognizable scientific figure family from natural-language text."""

    normalized = _normalize(request_text)
    if _contains_any(normalized, _SURVIVAL_TERMS):
        return DemoFigureKind.SURVIVAL
    if _contains_any(normalized, _DISTRIBUTION_TERMS):
        return DemoFigureKind.DISTRIBUTION
    if _contains_any(normalized, _RELATIONSHIP_TERMS):
        return DemoFigureKind.RELATIONSHIP
    return DemoFigureKind.GROUP_COMPARISON


def render_demo_figure(
    request_text: str,
    *,
    survival_outcome: str | None = None,
) -> DemoFigure:
    """Render a request-aware SVG using clearly labelled illustrative values only."""

    normalized = _normalize(request_text)
    kind = classify_demo_figure(request_text)

    if kind is DemoFigureKind.SURVIVAL:
        normalized_outcome = _normalize(survival_outcome or request_text)
        if "progression free" in normalized_outcome:
            title = "Progression-free survival by cohort"
        elif "overall survival" in normalized_outcome:
            title = "Overall survival by cohort"
        else:
            title = "Kaplan–Meier survival by cohort"
        description = (
            "An illustrative Kaplan–Meier figure compares two demonstration cohorts, "
            "including censoring marks and a number-at-risk table. No research dataset was used."
        )
        body = _survival_body()
        subtitle = "Illustrative cohorts · 95% confidence bands · censoring shown"
    elif kind is DemoFigureKind.DISTRIBUTION:
        expression = "expression" in normalized or "transcript" in normalized
        title = (
            "Expression distribution by group"
            if expression
            else "Distribution of measured values by group"
        )
        description = (
            "An illustrative violin-and-box figure compares the distribution, median, and "
            "interquartile range of three demonstration groups. No research dataset was used."
        )
        body = _distribution_body(expression=expression)
        subtitle = "Illustrative values · violin density with median and interquartile range"
    elif kind is DemoFigureKind.RELATIONSHIP:
        dose_response = "dose" in normalized
        title = (
            "Dose–response relationship"
            if dose_response
            else "Relationship between measured variables"
        )
        description = (
            "An illustrative dose–response figure shows demonstration observations and a fitted "
            "sigmoid curve. No research dataset was used."
            if dose_response
            else "An illustrative scatter figure shows demonstration observations, a fitted "
            "trend, and its confidence band. No research dataset was used."
        )
        body = _relationship_body(dose_response=dose_response)
        subtitle = (
            "Illustrative observations · fitted sigmoid with 95% confidence band"
            if dose_response
            else "Illustrative observations · linear fit with 95% confidence band"
        )
    else:
        title = "Measured response by research group"
        description = (
            "An illustrative dot-and-interval figure compares demonstration observations, "
            "means, and 95% confidence intervals across two groups. No research dataset was used."
        )
        body = _group_comparison_body()
        subtitle = "Illustrative groups · mean and 95% confidence interval · n = 12 per group"

    svg = _frame(
        kind=kind,
        title=title,
        subtitle=subtitle,
        description=description,
        body=body,
    )
    return DemoFigure(kind=kind, title=title, description=description, svg=svg)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _contains_any(value: str, candidates: tuple[str, ...]) -> bool:
    padded = f" {value} "
    return any(f" {candidate} " in padded for candidate in candidates)


def _frame(
    *,
    kind: DemoFigureKind,
    title: str,
    subtitle: str,
    description: str,
    body: str,
) -> str:
    safe_title = escape(title, quote=True)
    safe_subtitle = escape(subtitle, quote=True)
    safe_description = escape(description, quote=True)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 560" role="img"
  aria-labelledby="demo-figure-title demo-figure-description"
  data-demo="true" data-figure-kind="{kind.value}">
  <title id="demo-figure-title">{safe_title} — demonstration only</title>
  <desc id="demo-figure-description">{safe_description}</desc>
  <rect data-role="figure-background" width="960" height="560" fill="white"/>
  <g aria-hidden="true" font-family="Inter, ui-sans-serif, system-ui, sans-serif">
    <text data-role="plot-title" x="66" y="67" fill="#18221c" font-size="25" font-weight="700"
      letter-spacing="-0.45">{safe_title}</text>
    <text x="66" y="94" fill="#66716a" font-size="13.5">{safe_subtitle}</text>
    <text x="734" y="66" fill="#8b472f" font-size="10.5" font-weight="750"
      letter-spacing="0.65">DEMONSTRATION · NO DATASET</text>
<g data-role="plot-body">
{body}
</g>
    <text x="66" y="528" fill="#757e78" font-size="10.5">
      Illustrative values for interface demonstration. No research data was used.
    </text>
  </g>
</svg>
'''


def _survival_body() -> str:
    return """    <g fill="#79817c" font-size="10.5" text-anchor="end">
      <text x="106" y="147">1.00</text><text x="106" y="199">0.75</text>
      <text x="106" y="251">0.50</text><text x="106" y="303">0.25</text>
      <text x="106" y="355">0.00</text>
    </g>
    <g stroke="#e8e5de" stroke-width="1">
      <line x1="120" y1="143" x2="870" y2="143"/>
      <line x1="120" y1="195" x2="870" y2="195"/>
      <line x1="120" y1="247" x2="870" y2="247"/>
      <line x1="120" y1="299" x2="870" y2="299"/>
      <line x1="120" y1="351" x2="870" y2="351"/>
    </g>
    <line x1="120" y1="143" x2="120" y2="351" stroke="#626d66" stroke-width="1.2"/>
    <line x1="120" y1="351" x2="870" y2="351" stroke="#626d66" stroke-width="1.2"/>
    <text x="43" y="247" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle" transform="rotate(-90 43 247)">Survival probability</text>
    <text x="495" y="380" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle">Months from index date</text>
    <g fill="#737c76" font-size="10.5" text-anchor="middle">
      <text x="120" y="369">0</text><text x="307" y="369">6</text>
      <text x="495" y="369">12</text><text x="682" y="369">18</text>
      <text x="870" y="369">24</text>
    </g>
    <path d="M120 143 H182 V149 H245 V157 H307 V165 H370 V174 H432 V185 H495
      V198 H557 V212 H620 V228 H682 V245 H745 V263 H807 V282 H870"
      fill="none" stroke="#2f6f5a" stroke-opacity="0.13" stroke-width="18"/>
    <path d="M120 143 H182 V149 H245 V157 H307 V165 H370 V174 H432 V185 H495
      V198 H557 V212 H620 V228 H682 V245 H745 V263 H807 V282 H870"
      fill="none" stroke="#2f6f5a" stroke-width="3" stroke-linejoin="round"/>
    <path d="M120 143 H182 V154 H245 V168 H307 V181 H370 V198 H432 V218 H495
      V237 H557 V259 H620 V278 H682 V300 H745 V318 H807 V335 H870"
      fill="none" stroke="#d17452" stroke-opacity="0.13" stroke-width="18"/>
    <path d="M120 143 H182 V154 H245 V168 H307 V181 H370 V198 H432 V218 H495
      V237 H557 V259 H620 V278 H682 V300 H745 V318 H807 V335 H870"
      fill="none" stroke="#d17452" stroke-width="3" stroke-linejoin="round"/>
    <g data-layer="censoring" stroke="#2f6f5a" stroke-width="1.7">
      <path d="M278 156 v12 m-6 -6 h12"/><path d="M526 202 v12 m-6 -6 h12"/>
      <path d="M714 251 v12 m-6 -6 h12"/>
    </g>
    <g data-layer="censoring" stroke="#d17452" stroke-width="1.7">
      <path d="M338 181 v12 m-6 -6 h12"/><path d="M589 265 v12 m-6 -6 h12"/>
      <path d="M776 324 v12 m-6 -6 h12"/>
    </g>
    <g font-size="11.5" font-weight="650">
      <line x1="652" y1="145" x2="678" y2="145" stroke="#2f6f5a" stroke-width="3"/>
      <text x="686" y="149" fill="#344039">Cohort A</text>
      <line x1="759" y1="145" x2="785" y2="145" stroke="#d17452" stroke-width="3"/>
      <text x="793" y="149" fill="#344039">Cohort B</text>
    </g>
    <text x="66" y="411" fill="#303b35" font-size="11.5" font-weight="700">Number at risk</text>
    <g font-size="10.5">
      <circle cx="79" cy="434" r="4" fill="#2f6f5a"/><text x="91" y="438" fill="#455048">A</text>
      <circle cx="79" cy="458" r="4" fill="#d17452"/><text x="91" y="462" fill="#455048">B</text>
      <g fill="#58625c" text-anchor="middle">
        <text x="120" y="438">84</text><text x="307" y="438">77</text>
        <text x="495" y="438">63</text><text x="682" y="438">45</text>
        <text x="870" y="438">28</text><text x="120" y="462">82</text>
        <text x="307" y="462">68</text><text x="495" y="462">49</text>
        <text x="682" y="462">31</text><text x="870" y="462">14</text>
      </g>
    </g>"""


def _distribution_body(*, expression: bool) -> str:
    y_label = "Expression (log₂ a.u.)" if expression else "Measured value (a.u.)"
    return f"""    <g fill="#79817c" font-size="10.5" text-anchor="end">
      <text x="106" y="151">12</text><text x="106" y="207">9</text>
      <text x="106" y="263">6</text><text x="106" y="319">3</text>
      <text x="106" y="375">0</text>
    </g>
    <g stroke="#e8e5de" stroke-width="1">
      <line x1="120" y1="147" x2="870" y2="147"/>
      <line x1="120" y1="203" x2="870" y2="203"/>
      <line x1="120" y1="259" x2="870" y2="259"/>
      <line x1="120" y1="315" x2="870" y2="315"/>
      <line x1="120" y1="371" x2="870" y2="371"/>
    </g>
    <line x1="120" y1="147" x2="120" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <line x1="120" y1="371" x2="870" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <text x="43" y="259" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle" transform="rotate(-90 43 259)">{y_label}</text>
    <path d="M295 169 C262 181 250 211 259 238 C268 264 254 290 272 324
      C281 343 292 353 295 356 C298 353 309 343 318 324 C336 290 322 264 331 238
      C340 211 328 181 295 169 Z" fill="#397b64" fill-opacity="0.28"
      stroke="#397b64" stroke-width="2"/>
    <path d="M495 198 C457 210 449 235 459 257 C469 279 455 307 472 337
      C480 351 490 359 495 362 C500 359 510 351 518 337 C535 307 521 279 531 257
      C541 235 533 210 495 198 Z" fill="#d27654" fill-opacity="0.28"
      stroke="#d27654" stroke-width="2"/>
    <path d="M695 139 C666 151 655 179 664 207 C673 235 658 266 674 300
      C682 318 691 327 695 331 C699 327 708 318 716 300 C732 266 717 235 726 207
      C735 179 724 151 695 139 Z" fill="#57749a" fill-opacity="0.27"
      stroke="#57749a" stroke-width="2"/>
    <g data-layer="observations" fill="#fffefb" fill-opacity="0.75" stroke-width="1.4">
      <g stroke="#397b64">
        <circle cx="277" cy="296" r="3.5"/><circle cx="308" cy="280" r="3.5"/>
        <circle cx="283" cy="263" r="3.5"/><circle cx="312" cy="245" r="3.5"/>
        <circle cx="285" cy="226" r="3.5"/><circle cx="303" cy="202" r="3.5"/>
      </g>
      <g stroke="#d27654">
        <circle cx="476" cy="327" r="3.5"/><circle cx="514" cy="310" r="3.5"/>
        <circle cx="480" cy="289" r="3.5"/><circle cx="509" cy="271" r="3.5"/>
        <circle cx="481" cy="250" r="3.5"/><circle cx="507" cy="226" r="3.5"/>
      </g>
      <g stroke="#57749a">
        <circle cx="677" cy="289" r="3.5"/><circle cx="711" cy="266" r="3.5"/>
        <circle cx="681" cy="237" r="3.5"/><circle cx="712" cy="215" r="3.5"/>
        <circle cx="680" cy="190" r="3.5"/><circle cx="704" cy="161" r="3.5"/>
      </g>
    </g>
    <g data-layer="box" fill="#fffefb" stroke="#1c2922" stroke-width="1.7">
      <rect x="278" y="224" width="34" height="62"/><rect x="478" y="251" width="34" height="59"/>
      <rect x="678" y="188" width="34" height="65"/>
    </g>
    <g data-layer="box" stroke="#1c2922" stroke-width="3">
      <line x1="276" y1="253" x2="314" y2="253"/>
      <line x1="476" y1="281" x2="514" y2="281"/>
      <line x1="676" y1="218" x2="714" y2="218"/>
    </g>
    <g fill="#2b352f" font-size="12.5" font-weight="650" text-anchor="middle">
      <text x="295" y="398">Reference</text><text x="495" y="398">Group 1</text>
      <text x="695" y="398">Group 2</text>
    </g>
    <g fill="#7a827d" font-size="10.5" text-anchor="middle">
      <text x="295" y="417">n = 36</text><text x="495" y="417">n = 34</text>
      <text x="695" y="417">n = 35</text>
    </g>
    <path d="M495 445 V436 H695 V445" fill="none" stroke="#8a928d" stroke-width="1.2"/>
    <text x="595" y="432" text-anchor="middle" fill="#59625d" font-size="10.5"
      font-weight="650">illustrative shift</text>"""


def _relationship_body(*, dose_response: bool) -> str:
    if dose_response:
        return """    <g fill="#79817c" font-size="10.5" text-anchor="end">
      <text x="106" y="151">100</text><text x="106" y="207">75</text>
      <text x="106" y="263">50</text><text x="106" y="319">25</text>
      <text x="106" y="375">0</text>
    </g>
    <g stroke="#e8e5de" stroke-width="1">
      <line x1="120" y1="147" x2="870" y2="147"/><line x1="120" y1="203" x2="870" y2="203"/>
      <line x1="120" y1="259" x2="870" y2="259"/><line x1="120" y1="315" x2="870" y2="315"/>
      <line x1="120" y1="371" x2="870" y2="371"/>
    </g>
    <line x1="120" y1="147" x2="120" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <line x1="120" y1="371" x2="870" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <text x="43" y="259" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle" transform="rotate(-90 43 259)">Response (% of maximum)</text>
    <text x="495" y="420" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle">Concentration (log₁₀ a.u.)</text>
    <g fill="#737c76" font-size="10.5" text-anchor="middle">
      <text x="120" y="390">−2</text><text x="307" y="390">−1</text>
      <text x="495" y="390">0</text><text x="682" y="390">1</text>
      <text x="870" y="390">2</text>
    </g>
    <path d="M130 355 C270 354 334 344 395 311 C454 279 476 224 532 190
      C593 153 665 150 858 150" data-layer="band" fill="none" stroke="#3b765f" stroke-opacity="0.14"
      stroke-width="24"/>
    <path d="M130 355 C270 354 334 344 395 311 C454 279 476 224 532 190
      C593 153 665 150 858 150" data-layer="trend" fill="none" stroke="#2f6f5a" stroke-width="3.3"/>
    <g data-layer="observations" fill="#d17452" fill-opacity="0.82"
      stroke="#fffefb" stroke-width="1.8">
      <circle cx="151" cy="350" r="5.5"/><circle cx="187" cy="359" r="5.5"/>
      <circle cx="241" cy="346" r="5.5"/><circle cx="286" cy="351" r="5.5"/>
      <circle cx="341" cy="332" r="5.5"/><circle cx="375" cy="319" r="5.5"/>
      <circle cx="416" cy="298" r="5.5"/><circle cx="452" cy="272" r="5.5"/>
      <circle cx="485" cy="239" r="5.5"/><circle cx="523" cy="207" r="5.5"/>
      <circle cx="568" cy="177" r="5.5"/><circle cx="615" cy="166" r="5.5"/>
      <circle cx="669" cy="151" r="5.5"/><circle cx="729" cy="158" r="5.5"/>
      <circle cx="792" cy="145" r="5.5"/><circle cx="844" cy="153" r="5.5"/>
    </g>
    <line x1="495" y1="147" x2="495" y2="371" stroke="#8c948f" stroke-dasharray="4 5"/>
    <rect x="513" y="322" width="118" height="30" rx="15" fill="#f3f1eb"/>
    <text x="572" y="341" text-anchor="middle" fill="#424d46" font-size="11"
      font-weight="700">EC₅₀ · illustrative</text>"""

    return """    <g fill="#79817c" font-size="10.5" text-anchor="end">
      <text x="106" y="151">80</text><text x="106" y="207">60</text>
      <text x="106" y="263">40</text><text x="106" y="319">20</text>
      <text x="106" y="375">0</text>
    </g>
    <g stroke="#e8e5de" stroke-width="1">
      <line x1="120" y1="147" x2="870" y2="147"/><line x1="120" y1="203" x2="870" y2="203"/>
      <line x1="120" y1="259" x2="870" y2="259"/><line x1="120" y1="315" x2="870" y2="315"/>
      <line x1="120" y1="371" x2="870" y2="371"/>
    </g>
    <line x1="120" y1="147" x2="120" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <line x1="120" y1="371" x2="870" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <text x="43" y="259" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle" transform="rotate(-90 43 259)">Response measure</text>
    <text x="495" y="420" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle">Predictor measure</text>
    <path data-layer="band" d="M150 337 L850 162 L850 191 L150 366 Z"
      fill="#397b64" fill-opacity="0.12"/>
    <line data-layer="trend" x1="150" y1="351" x2="850" y2="176" stroke="#2f6f5a" stroke-width="3"/>
    <g data-layer="observations" fill="#d17452" fill-opacity="0.82"
      stroke="#fffefb" stroke-width="1.8">
      <circle cx="166" cy="337" r="6"/><circle cx="207" cy="348" r="6"/>
      <circle cx="246" cy="312" r="6"/><circle cx="286" cy="326" r="6"/>
      <circle cx="329" cy="288" r="6"/><circle cx="371" cy="301" r="6"/>
      <circle cx="412" cy="268" r="6"/><circle cx="448" cy="279" r="6"/>
      <circle cx="491" cy="231" r="6"/><circle cx="533" cy="252" r="6"/>
      <circle cx="574" cy="211" r="6"/><circle cx="617" cy="223" r="6"/>
      <circle cx="658" cy="186" r="6"/><circle cx="703" cy="204" r="6"/>
      <circle cx="744" cy="168" r="6"/><circle cx="790" cy="181" r="6"/>
      <circle cx="833" cy="153" r="6"/>
    </g>
    <rect x="669" y="317" width="174" height="40" rx="10" fill="#f3f1eb"/>
    <text x="685" y="334" fill="#6c756f" font-size="10">ILLUSTRATIVE FIT</text>
    <text x="685" y="349" fill="#28332d" font-size="11.5" font-weight="700">
      positive association</text>"""


def _group_comparison_body() -> str:
    return """    <g fill="#79817c" font-size="10.5" text-anchor="end">
      <text x="106" y="151">70</text><text x="106" y="207">60</text>
      <text x="106" y="263">50</text><text x="106" y="319">40</text>
      <text x="106" y="375">30</text>
    </g>
    <g stroke="#e8e5de" stroke-width="1">
      <line x1="120" y1="147" x2="870" y2="147"/><line x1="120" y1="203" x2="870" y2="203"/>
      <line x1="120" y1="259" x2="870" y2="259"/><line x1="120" y1="315" x2="870" y2="315"/>
      <line x1="120" y1="371" x2="870" y2="371"/>
    </g>
    <line x1="120" y1="371" x2="870" y2="371" stroke="#626d66" stroke-width="1.2"/>
    <text x="43" y="259" fill="#505a54" font-size="11.5" font-weight="600"
      text-anchor="middle" transform="rotate(-90 43 259)">Measured value (a.u.)</text>
    <path d="M320 189 V178 H640 V189" fill="none" stroke="#8a928d" stroke-width="1.2"/>
    <rect x="425" y="158" width="110" height="29" rx="14.5" fill="#f3f1eb"/>
    <text x="480" y="177" text-anchor="middle" fill="#414b45" font-size="11.5"
      font-weight="700">+13.7 units</text>
    <g data-layer="observations" fill="#397b64" fill-opacity="0.78"
      stroke="#fffefb" stroke-width="1.8">
      <circle cx="284" cy="333" r="6"/><circle cx="309" cy="322" r="6"/>
      <circle cx="337" cy="311" r="6"/><circle cx="363" cy="305" r="6"/>
      <circle cx="273" cy="301" r="6"/><circle cx="302" cy="294" r="6"/>
      <circle cx="333" cy="294" r="6"/><circle cx="359" cy="288" r="6"/>
      <circle cx="282" cy="282" r="6"/><circle cx="315" cy="276" r="6"/>
      <circle cx="347" cy="265" r="6"/><circle cx="378" cy="248" r="6"/>
    </g>
    <g data-layer="observations" fill="#d17452" fill-opacity="0.8"
      stroke="#fffefb" stroke-width="1.8">
      <circle cx="604" cy="254" r="6"/><circle cx="633" cy="243" r="6"/>
      <circle cx="667" cy="237" r="6"/><circle cx="590" cy="232" r="6"/>
      <circle cx="620" cy="226" r="6"/><circle cx="652" cy="221" r="6"/>
      <circle cx="685" cy="215" r="6"/><circle cx="598" cy="210" r="6"/>
      <circle cx="630" cy="204" r="6"/><circle cx="662" cy="199" r="6"/>
      <circle cx="610" cy="188" r="6"/><circle cx="676" cy="166" r="6"/>
    </g>
    <g stroke="#18221c" stroke-width="2.1">
      <line x1="320" y1="276" x2="320" y2="304"/><line x1="306" y1="276" x2="334" y2="276"/>
      <line x1="306" y1="304" x2="334" y2="304"/>
      <line x1="283" y1="291" x2="357" y2="291" stroke-width="4"/>
      <line x1="640" y1="195" x2="640" y2="227"/><line x1="626" y1="195" x2="654" y2="195"/>
      <line x1="626" y1="227" x2="654" y2="227"/>
      <line x1="603" y1="216" x2="677" y2="216" stroke-width="4"/>
    </g>
    <g fill="#18221c" font-size="11.5" font-weight="700">
      <text x="373" y="295">42.1</text><text x="693" y="220">55.8</text>
    </g>
    <g text-anchor="middle">
      <circle cx="282" cy="410" r="4.5" fill="#397b64"/>
      <text x="333" y="415" fill="#29332d" font-size="13" font-weight="700">Control</text>
      <text x="320" y="436" fill="#7a827d" font-size="10.5">n = 12 observations</text>
      <circle cx="598" cy="410" r="4.5" fill="#d17452"/>
      <text x="657" y="415" fill="#29332d" font-size="13" font-weight="700">Treatment</text>
      <text x="640" y="436" fill="#7a827d" font-size="10.5">n = 12 observations</text>
    </g>"""
