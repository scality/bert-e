{% extends "message.md" %}

{% block title -%}
Build failed
{% endblock %}

{% block message %}
The build did not succeed in integration pull request #{{ pr_id }}.
{% if build_url is defined %}
Link to the build: {{ build_url }}
{%- endif -%}
{% endblock %}
