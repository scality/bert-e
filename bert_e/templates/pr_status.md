{% extends "message.md" %}

{% block title -%}
Bert-E status
{% endblock %}

{% block message %}
{{ icon }} **{{ label }}**{% if code %} (message {{ code }}){% endif %}

{% if integration is not none %}
{% if integration %}
integration branch | pull request | build
-------------------|--------------|------
{% for item in integration -%}
`{{ item.branch }}` | {% if item.pr_id %}#{{ item.pr_id }}{% else %}-{% endif %} | {% if item.build %}{{ item.build }}{% else %}-{% endif %}
{% endfor %}
{% else %}
*No integration branch.*
{% endif %}
{% endif %}

{% if status %}
{% include 'status_report.md' %}
{% endif %}

*This comment is kept up to date by Bert-E.*
{% endblock %}
