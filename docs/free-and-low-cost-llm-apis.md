# Free and Low-Cost LLM APIs

Transcript Weaver requires access to a large language model (LLM) API for
transcript cleanup and classification. Most development and testing of this
project has used the free tier of Google's Gemini API.

This page is general information for people who need an API but do not yet
have one. It is not a list of providers supported by Transcript Weaver. The
packaged example currently uses Gemini, and using another provider would
require a compatible integration.

## Places to Start

Google AI Studio offers free Gemini API access, subject to model-specific
request and token limits. Those limits can differ substantially between
models and may change without notice.

[Vercel AI Gateway](https://vercel.com/docs/ai-gateway/pricing) is another
option worth investigating. As of August 11, 2026, its free tier includes $5
in usage credit each month and access to its available models. Transcript
Weaver has not been tested with Vercel AI Gateway. Read Vercel's current terms
before relying on the offer; purchasing credits moves an account to its paid
tier and ends the monthly free credit.

For a broader survey, the best public comparison we have found as of August
11, 2026, is OpenRouter's
[Free LLM APIs Compared: Rate Limits, Models, and Real Costs (2026)](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/).
It compares permanent free tiers, trial credits, rate limits, privacy
trade-offs, and paid transition paths across multiple providers. The article
was published June 15, 2026, and says much of its underlying provider data was
verified in March and April 2026.

## Caveat Emptor

Free and low-cost API offers change frequently. Before choosing one, verify
the provider's current:

- supported models and API compatibility;
- requests-per-minute, tokens-per-minute, and requests-per-day limits;
- trial expiration, credit-card, and billing requirements;
- prompt and response retention or training policies;
- context-window and structured-output support; and
- commercial-use terms and service availability.

Free access often trades money for tighter quotas, weaker availability, or
permission to use submitted data for model improvement. Do not send private
or sensitive transcripts until you understand the provider's current data
handling terms.

Treat every price, quota, and feature mentioned here as a starting point for
research rather than a guarantee.
