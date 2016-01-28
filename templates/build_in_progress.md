{% extends "message.md" %}

{% block title -%}
Build in progress
{% endblock %}

{% block message %}
Waiting for the build status in integration pull request #{{ pr_id }}.
{% endblock %}
