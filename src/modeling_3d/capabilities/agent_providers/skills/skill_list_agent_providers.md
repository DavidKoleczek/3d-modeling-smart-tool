`list-agent-providers` says which agent providers the model-backed capabilities can run through on
this machine: whether each is installed, whether it is signed in, and how. It starts each
installed one's runtime and asks it, as a run does before its agent starts, so it takes a second
or two.

```bash
modeling-3d list-agent-providers
```

```python
from modeling_3d.lib import list_agent_providers

[(status.agent_provider, status.signed_in) for status in list_agent_providers().agent_providers]
```

Reach for it when a run fails because its agent provider has no credentials, or before the first
run on a machine. Each one that cannot run says why and what fixes it in `problem`.

## Result

JSON on stdout, the agent providers in the order a run picks them:

```json
{
  "agent_providers": [
    {"agent_provider": "claude", "installed": true, "signed_in": true,
     "signed_in_with": "Claude Max", "problem": null},
    {"agent_provider": "codex", "installed": true, "signed_in": false, "signed_in_with": null,
     "problem": "Codex is not signed in. Install the Codex CLI and run `codex login`, ..."}
  ]
}
```

`signed_in_with` is how, in the runtime's own words, such as a Claude subscription, an API key,
ChatGPT, or a cloud provider, and never the account's email.
