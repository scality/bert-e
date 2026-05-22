{% extends "message.md" %}

{% block title -%}
Babysit: Retrying build
{% endblock %}

{% block message %}
The {% if build_url -%}[build]({{ build_url }}) {% else -%}build {% endif -%}
failed on branch `{{ branch.name }}` (commit `{{ commit_sha[:7] }}`).

**Babysit mode is active** - automatically retrying failed workflows:

| Workflow | Retry |
|:---------|:-----:|
{% for wf in workflows -%}
| `{{ wf.name }}` | {{ wf.retry_count }}/{{ max_retries }} |
{% endfor %}
Please wait for the new build to complete.
{% endblock %}

