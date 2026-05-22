{% extends "message.md" %}

{% block title -%}
Babysit: Maximum retries reached
{% endblock %}

{% block message %}
The {% if build_url -%}[build]({{ build_url }}) {% else -%}build {% endif -%}
has exhausted all automatic retry attempts on branch `{{ branch.name }}`.

**Exhausted workflows** ({{ max_retries }} retries each):
{% for wf in exhausted_workflows -%}
- `{{ wf }}`
{% endfor %}
To investigate:
- Review the [build logs]({{ build_url }}) for the failure cause
- Check if this is a flaky test or a genuine issue

To get more retries:
- Fix the issue and push new commits (babysit will continue with fresh retries), or
- Comment `@{{ robot }} babysit` again to reset the retry counter
{% endblock %}

