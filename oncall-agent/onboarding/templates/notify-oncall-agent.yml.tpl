name: Notificar al Autonomous On-Call Engineer

on:
  push:
    branches: [main]

jobs:
  dispatch:
    runs-on: ubuntu-latest
    steps:
      - name: Disparar regeneracion de onboarding en el agente
        run: |
          curl -X POST \
            -H "Accept: application/vnd.github+json" \
            -H "Authorization: Bearer ${{ secrets.CROSS_REPO_DISPATCH_TOKEN }}" \
            https://api.github.com/repos/__AGENT_REPO__/dispatches \
            -d '{"event_type":"project_updated","client_payload":{"project":"__PROJECT_NAME__"}}'
