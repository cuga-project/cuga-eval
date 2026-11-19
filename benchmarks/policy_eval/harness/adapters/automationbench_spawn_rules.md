## Sub-agents
- Start every task by calling `spawn_agent` with mode "async" for read-only work, before you read anything yourself: one sub-agent per kind of source (mail; documents and spreadsheets; chat and other apps) that finds the rules, procedures and records for this request and returns them with exact quotes and IDs.
- A sub-agent has your tools but no memory of this conversation. Put the full request and what to return in its task text, and tell it not to send, create, update or post anything.
- Collect every result with `get_agent_result`. When the request covers several records, you may spawn one more read-only sub-agent per record to read it in full and return what the rules decide for it, with the values used.
- Make every change yourself, after you have the results.
