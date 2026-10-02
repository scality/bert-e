{{ marker }}
## Bert-E status: {{ state }}
{% if status %}
Result: **{{ status }}**
{% endif %}
{% if integration_prs %}

Integration pull requests:
{% for pr in integration_prs -%}
* #{{ pr.id }}: `{{ pr.src }}` → `{{ pr.dst }}`
{% endfor %}
{% endif %}
{% if active_options %}

*Options set:* **{{ active_options|join(', ') }}**
{% endif %}

*This comment is updated at each step; see the comments below for details.*
