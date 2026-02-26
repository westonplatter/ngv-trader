# Fix CL FOP selection process

## Example

I’ll add the CL 65 Call (FOP) that expires this Friday — I interpret that as the CL futures option (FOP) strike 65, call, expiring Fri 2026-02-27 (contract month: March 2026). Is that correct?

Also — which watch list should I add it to?

- Reply with an existing watch list ID (I can list them if you want), or
- Say "new" and give a name (or I can create one named "CL Options").

After you confirm watch list and the above details, I’ll enqueue the IBKR fetch job and return the job_id so you can poll for completion.

## Core issue

The future contract month was expected to be March (maybe because it's Feb but the March contract expired and we're trading the April contract. today is Feb 25). We had previously dealth with this when trade both shows the CL front month future. let's correct for this so when a user asks for a CL FOP, we don't constrain the selection process to epxect the wrong undelryting futures contract.

Going forward, we want to be underlying contract agnostc and follow the user's request for the expiration date (this friday).
