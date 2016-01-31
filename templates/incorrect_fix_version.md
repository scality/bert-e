{% extends "message.md" %}

{% block title -%}
Incorrect fix version
{% endblock %}

{% block message %}
The issue `Fix Version/s` field
contains {{ issues|join(', ') }}.
It must contain: {{ expects|join(', ') }}."
{% endblock %}
