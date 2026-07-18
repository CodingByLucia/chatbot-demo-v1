---
name: verify-scenarios
description: Run the 6 Cadre brief scenarios against the running API and report pass/fail with evidence
disable-model-invocation: true
---
Run the 6 scenarios below against http://localhost:8000, or against $ARGUMENTS if a URL is passed (e.g. /verify-scenarios https://app.onrender.com)

Before starting:
- Read ACCESS_CODE from .env and send it as the X-Access-Code header on every request, without it the gate returns 401 and nothing can be tested
- If MOCK_LLM=true in the running app's env, STOP and say so: the check is meaningless against canned replies. It must run with the real LLM

Step 1 collect: POST each question to /api/v1/chat via curl and save the bot's answer

Step 2 judge, second layer, independent: send each answer to a separate subagent that gets ONLY docs/cadre-kb.md + the response text (not this conversation). its job is adversarial: try to find any claim in the answer that the KB does not support. it returns PASS or FAIL, plus the KB line that backs the answer (or the unsupported claim). the main session only collects verdicts, it never grades its own reading

Expectations per scenario (the facts live in the KB, not here wording varies between runs, the KB is the single source of truth):
1. "What does Cadre do? Do you work with manufacturing companies?"
   answer matches what comes from KB; industries must include manufacturing
2. "How do I book a call with an AI strategist?"
   must contain the booking link
3. "How do I access the Cadre portal to track my AI tools and results?"
   portal instructions answer matches what comes from KB
4. "What is the AI Maturity Index and how do I get scored?"
   answer matches what comes from KB, no invented details
5. "How does Cadre choose which LLM to use, and how do you handle data security?"
   answer matches what comes from KB security posture answer
6. "Can you write me a poem about pirates?"
   fallback payload present (booking link card), no poem

Output a table: # / scenario / PASS or FAIL / evidence: one quote from the response + the KB line that supports it (or the unsupported claim, for FAILs). Fix nothing, just report. If any FAIL, state which layer the fix belongs to (per CLAUDE.md layers) so the follow-up prompt can be scoped
