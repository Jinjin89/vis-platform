# LLM Configuration

The backend reads language-model settings from environment variables. For local development, place them in backend/.env.

## DeepSeek

Set the API key in backend/.env:

~~~dotenv
DEEPSEEK_API_KEY=your_api_key_here
~~~

The committed backend/.env.example contains all supported settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| DEEPSEEK_API_KEY | empty | Secret API key; required before real agent calls |
| VIS_PLATFORM_LLM_PROVIDER | deepseek | Provider adapter |
| VIS_PLATFORM_LLM_BASE_URL | https://api.deepseek.com | OpenAI-compatible API base URL |
| VIS_PLATFORM_LLM_MODEL | deepseek-v4-flash-vision-exp | Model used by every backend agent |
| VIS_PLATFORM_LLM_THINKING_ENABLED | true | Enables thinking mode |
| VIS_PLATFORM_LLM_REASONING_EFFORT | high | low, high, or max |
| VIS_PLATFORM_LLM_TIMEOUT_SECONDS | 120 | Request timeout |
| VIS_PLATFORM_DEVELOPER_TRACE_ENABLED | false | Persist sanitized agent traces |
| VIS_PLATFORM_DEVELOPER_TRACE_TOKEN | empty | Required token for reading traces over the API |

The API key is never included in health responses, public API contracts, logs, or frontend bundles.

The configured model handles conversation, intent planning, data interpretation, and R-code planning using the persisted history of the current conversation, saved figure context, and backend capability information. Plot reference images are sent as image content blocks to both intent and code planning. The same references survive clarification and schema retries. Automated visual/publication review remains unconnected. See [REFERENCE_IMAGES.md](REFERENCE_IMAGES.md) for the implemented image workflow.

The model accepts JPEG, PNG, GIF, and WebP image input. Before visual review, render the plot to PNG; do not send SVG directly. Only the plot image and compact plot context are sent, never the raw research dataset.

## Developer trace

The application is exposed on the network without user authentication, so developer traces require a separate token. Set both values in backend/.env:

~~~dotenv
VIS_PLATFORM_DEVELOPER_TRACE_ENABLED=true
VIS_PLATFORM_DEVELOPER_TRACE_TOKEN=choose-a-long-random-value
~~~

Expand an Activity block, open Developer diagnostics, and enter the same trace token. The frontend keeps it in browser session storage and sends it only in the X-Developer-Trace-Token header.

The trace includes sanitized model messages, final structured model output, intent decisions, routing, stage timing, tool summaries, and errors. It never includes the DeepSeek API key, raw research data, physical paths, or private reasoning_content.

## Test intent without starting servers

~~~sh
cd backend
uv run --env-file .env python scripts/check_intent.py "how are you?"
~~~

This prints only the validated structured intent decision.

## Verify configuration

Start the backend with the environment file:

~~~sh
cd backend
uv run uvicorn vis_platform_backend.app:app \
  --host 0.0.0.0 \
  --port 18080 \
  --env-file .env
~~~

Then request:

~~~sh
curl --noproxy '*' http://127.0.0.1:18080/api/v1/health
~~~

The llm.configured field is true when a non-empty API key was loaded. The key itself is never returned.


## Planner context and activity

The intent planner receives the original request, recent conversation, current figure controls, scoped workspace metadata, and saved clarification answers. Resumed calls include the previous planner decision and a final user-answer message so completed questions are not treated as new instructions. Public activity is independent of developer tracing: users can see tool checks, planner decisions, and rendering progress without a trace token. Model failures and cancellation are stored as terminal request states; pending questions can be resumed after a server restart.

Structured data/code responses start with a 16,000-token output budget. A provider-reported truncation triggers one retry at 32,000 tokens without replaying the incomplete JSON. Schema correction and truncation share a two-request bound. This follows the provider's documented [finish reason semantics](https://api-docs.deepseek.com/api/create-chat-completion/).
